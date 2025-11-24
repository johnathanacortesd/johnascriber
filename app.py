import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter

# --- LÓGICA DE AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        st.session_state.password_attempted = False
        if "password" in st.session_state:
            del st.session_state["password"]
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    st.markdown("""
    <div style='text-align: center; padding: 2rem 0;'>
        <h1 style='color: #1f77b4; font-size: 3rem;'>🎙️</h1>
        <h2>Transcriptor Pro V13 - High Fidelity</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Edición Exacta. Sin bucles. Sin pérdidas.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro V13", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# --- CALLBACKS UI ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

# --- 1. OPTIMIZACIÓN DE AUDIO (SOLUCIÓN A PARTES FALTANTES) ---
def optimize_audio_robust(file_bytes, filename):
    """
    Normaliza el volumen y convierte a formato nativo de Whisper (16kHz Mono).
    El filtro 'loudnorm' es CRUCIAL para evitar que Whisper se salte partes con bajo volumen.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp.write(file_bytes)
        input_path = tmp.name
    
    output_path = input_path + "_opt.mp3"
    try:
        # Cadena de filtros FFmpeg:
        # 1. loudnorm: Normaliza el volumen (evita silencios falsos).
        # 2. highpass/lowpass: Limpia ruido de fondo muy grave o agudo.
        # 3. ar 16000 / ac 1: Formato nativo de Whisper.
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-vn",  # Eliminar video
            "-ar", "16000",  # Frecuencia de muestreo
            "-ac", "1",  # Mono
            "-b:a", "48k", # Bitrate suficiente para voz
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,highpass=f=200,lowpass=f=3000", 
            "-f", "mp3",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(output_path, 'rb') as f: 
            new_bytes = f.read()
        
        # Limpieza
        try:
            os.unlink(input_path)
            os.unlink(output_path)
        except: pass
            
        return new_bytes, True
    except Exception as e:
        print(f"Error ffmpeg: {e}")
        # Si falla, devolver original pero intentando limpiar temporales
        if os.path.exists(input_path): os.unlink(input_path)
        return file_bytes, False

# --- 2. LIMPIEZA DE ALUCINACIONES Y BUCLES (SOLUCIÓN A REPETICIONES) ---
def remove_repetitive_loops(text):
    """
    Detecta y elimina bucles donde Whisper repite la misma frase varias veces.
    Ej: "y entonces y entonces y entonces" -> "y entonces"
    """
    if not text: return ""
    
    # 1. Eliminar repeticiones inmediatas de palabras (hola hola hola)
    text = re.sub(r'\b(\w+)( \1\b)+', r'\1', text, flags=re.IGNORECASE)
    
    # 2. Eliminar repeticiones de frases (n-grams de 2 a 10 palabras)
    # Esto busca patrones (A B C) (A B C) y deja solo uno.
    for n in range(10, 2, -1): # Buscar frases largas primero
        # Regex compleja para capturar grupos repetidos
        pattern = r'((\b\w+\s+){' + str(n-1) + r'}\b\w+)(\s+\1)+'
        while re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, r'\1', text, flags=re.IGNORECASE)
            
    return text.strip()

def clean_whisper_hallucinations(text):
    """Limpia basura conocida que Whisper V3 inventa."""
    if not text: return ""
    
    # Lista negra de alucinaciones comunes
    junk_patterns = [
        r"Subtítulos realizados por.*",
        r"Comunidad de editores.*",
        r"Amara\.org.*",
        r"Transcribed by.*",
        r"Sujeto a.*licencia.*",
        r"Copyright.*",
        r"Gracias por ver.*",
        r"Suscríbete.*",
        r"Dale like.*",
        r"\[Música\]",
        r"\[Aplausos\]",
        r"\[Risas\]",
        r"Visita nuestro sitio.*",
        # Patrones de navegación web que a veces lee del "aire"
        r"\b(siguiente|anterior|continuar|página|menú|inicio)\b(\s+\1\b){2,}",
    ]
    
    cleaned = text
    for pattern in junk_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    cleaned = remove_repetitive_loops(cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned) # Normalizar espacios
    
    return cleaned.strip()

# --- 3. FILTRADO INTELIGENTE DE SEGMENTOS ---
def filter_segments_strict(segments):
    """
    Reconstruye el texto completo analizando la calidad de cada segmento.
    """
    clean_segments = []
    full_text_parts = []
    last_text_clean = ""
    
    for seg in segments:
        raw_text = seg['text']
        
        # 1. Limpieza básica
        txt = clean_whisper_hallucinations(raw_text)
        
        # 2. Filtros de rechazo
        if len(txt) < 2: continue # Demasiado corto (letras sueltas)
        if re.match(r'^[.,;?!]+$', txt): continue # Solo puntuación
        
        # 3. Detección de duplicados exactos o casi exactos con el anterior
        if last_text_clean:
            # Similitud simple
            if txt.lower().strip() == last_text_clean.lower().strip():
                continue
            # Si el texto actual está contenido al final del anterior (solapamiento)
            if last_text_clean.endswith(txt):
                continue

        seg['text'] = txt
        clean_segments.append(seg)
        full_text_parts.append(txt)
        last_text_clean = txt
        
    return clean_segments, " ".join(full_text_parts)

# --- 4. CORRECCIÓN QUIRÚRGICA (SOLO TILDES) ---
def text_chunker_smart(text, chunk_size=2000):
    """Corta por oraciones para no romper contexto para el LLM."""
    sentences = re.split(r'(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚÑ])', text)
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 < chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk: chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk: chunks.append(current_chunk.strip())
    return chunks

def surgical_correction(text, client):
    chunks = text_chunker_smart(text)
    final_parts = []
    
    progress_text = "🧠 Aplicando corrección ortográfica estricta..."
    my_bar = st.progress(0, text=progress_text)
    
    # Prompt extremadamente estricto para evitar reescrituras
    system_prompt = """Eres un corrector ortográfico automático invisible.
TU ÚNICA TAREA: Corregir acentos (tildes) y signos de puntuación básicos en español.
REGLAS ABSOLUTAS:
1. NO cambies ninguna palabra.
2. NO resumas.
3. NO elimines texto.
4. NO agregues saludos ni explicaciones.
5. Si el texto es "hola k ase", devuélvelo tal cual si no sabes corregirlo, pero NO lo cambies por "hola qué haces" si eso altera la fonética original. Solo tildes obvias.
6. Devuelve SOLAMENTE el texto corregido."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.3-70b-versatile", # Modelo más inteligente para seguir instrucciones
                temperature=0.1,
                max_tokens=len(chunk) + 100
            )
            corrected = response.choices[0].message.content.strip()
            
            # Safety Check: Si la longitud varía más del 10%, algo salió mal (el LLM intentó resumir)
            len_diff = abs(len(corrected) - len(chunk))
            if len_diff > (len(chunk) * 0.10): 
                final_parts.append(chunk) # Descartar cambio peligroso
            else:
                final_parts.append(corrected)
                
        except:
            final_parts.append(chunk)
            
        my_bar.progress((i + 1) / len(chunks))
        
    my_bar.empty()
    return " ".join(final_parts)

# --- UTILIDADES DE EXPORTACIÓN Y UI ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    # Script JS para copiar al portapapeles
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #ddd; background: #fff; cursor: pointer;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def get_extended_context(segments, match_index, context_range=2):
    start = max(0, match_index - context_range)
    end = min(len(segments), match_index + context_range + 1)
    return [{'text': segments[i]['text'], 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start, end)]

def export_to_srt(segments):
    srt = []
    for i, seg in enumerate(segments, 1):
        s = timedelta(seconds=seg['start'])
        e = timedelta(seconds=seg['end'])
        s_str = f"{s.seconds//3600:02}:{(s.seconds//60)%60:02}:{s.seconds%60:02},{s.microseconds//1000:03}"
        e_str = f"{e.seconds//3600:02}:{(e.seconds//60)%60:02}:{e.seconds%60:02},{e.microseconds//1000:03}"
        srt.append(f"{i}\n{s_str} --> {e_str}\n{seg['text']}\n")
    return "\n".join(srt)

def answer_question(q, text, client, history):
    msgs = [{"role": "system", "content": "Eres un asistente útil. Responde preguntas basándote ÚNICAMENTE en la transcripción proporcionada."}]
    for item in history:
        msgs.append({"role": "user", "content": item['question']})
        msgs.append({"role": "assistant", "content": item['answer']})
    # Recortar contexto si es muy largo para el chat
    msgs.append({"role": "user", "content": f"Transcripción:\n{text[:25000]}\n\nPregunta: {q}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.3-70b-versatile").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- INTERFAZ PRINCIPAL ---
with st.sidebar:
    st.header("⚙️ Configuración")
    st.markdown("### Modos de Procesamiento")
    correction_mode = st.radio("Nivel de Corrección:", ["Whisper Puro (Raw)", "Quirúrgico (Solo Tildes)"], index=1)
    
    st.markdown("---")
    st.info("✅ Mejoras Activas:\n- Normalización de Audio (Loudnorm)\n- Filtro Anti-Bucles\n- Eliminación de Alucinaciones\n- Whisper Large V3")

uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov", "flac", "aac"])

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    try:
        # 1. PROCESAMIENTO DE AUDIO
        with st.spinner("🔄 Normalizando audio (Esto arregla partes silenciosas)..."):
            audio_bytes, optimized = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = audio_bytes
            if not optimized: 
                st.warning("⚠️ No se pudo normalizar el audio. Usando original (puede haber pérdidas en silencios).")

        # 2. TRANSCRIPCIÓN
        with st.spinner("📝 Transcribiendo con Whisper V3 (Prompt Anti-Repetición)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            # Prompt diseñado para evitar que invente
            whisper_prompt = "Transcripción verbatim en español. No repetir frases. No inventar texto."
            
            with open(tmp_path, "rb") as f:
                transcription_data = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0, # Temperatura 0 para máxima fidelidad
                    prompt=whisper_prompt
                )
            os.unlink(tmp_path)

        # 3. LIMPIEZA Y FILTRADO
        with st.spinner("🧹 Limpiando bucles y alucinaciones..."):
            segments_cleaned, text_cleaned = filter_segments_strict(transcription_data.segments)
        
        # 4. CORRECCIÓN ORTOGRÁFICA (OPCIONAL)
        final_text = text_cleaned
        if correction_mode == "Quirúrgico (Solo Tildes)":
            final_text = surgical_correction(text_cleaned, client)
            
            # Actualizar texto de segmentos (aproximación simple)
            # Nota: Actualizar segmentos individuales con LLM es complejo, 
            # aquí actualizamos el bloque de texto principal.
        
        # 5. GUARDAR ESTADO
        st.session_state.transcription_text = final_text
        st.session_state.segments = segments_cleaned
        
        st.balloons()
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ Error crítico: {e}")

# --- VISUALIZACIÓN ---
if 'transcription_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    col1, col2 = st.columns(2)
    col1.metric("📝 Palabras Totales", len(st.session_state.transcription_text.split()))
    col2.metric("⏱️ Segmentos Útiles", len(st.session_state.segments))
    
    tab1, tab2 = st.tabs(["📝 Texto & Búsqueda", "💬 Chat IA"])
    
    with tab1:
        col_s1, col_s2 = st.columns([4, 1])
        query = col_s1.text_input("🔎 Buscar en audio:", key="search_input")
        col_s2.write(""); col_s2.button("✖️", on_click=clear_search_callback)
        
        if query:
            with st.expander(f"📍 Resultados: '{query}'", expanded=True):
                count = 0
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        count += 1
                        context = get_extended_context(st.session_state.segments, i, 1)
                        for ctx in context:
                            c1, c2 = st.columns([0.15, 0.85])
                            if ctx['is_match']:
                                c1.button(f"▶️ {ctx['time']}", key=f"btn_{i}_{ctx['start']}", on_click=set_audio_time, args=(ctx['start'],))
                                clean_display = re.sub(re.escape(query), f"**{query.upper()}**", ctx['text'], flags=re.IGNORECASE)
                                c2.markdown(f"... {clean_display} ...")
                        st.divider()
                if count == 0: st.warning("No encontrado.")

        st.markdown("### 📄 Transcripción Final")
        st.text_area("Texto procesado:", st.session_state.transcription_text, height=500, label_visibility="collapsed")
        
        c1, c2, c3 = st.columns([1,1,1])
        c1.download_button("💾 Descargar TXT", st.session_state.transcription_text, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 Descargar SRT", export_to_srt(st.session_state.segments), "subtitulos.srt", use_container_width=True)
        with c3: create_copy_button(st.session_state.transcription_text)

    with tab2:
        st.subheader("💬 Pregunta sobre el contenido")
        for msg in st.session_state.qa_history:
            st.chat_message("user").write(msg['question'])
            st.chat_message("assistant").write(msg['answer'])
            
        if prompt := st.chat_input("Escribe tu pregunta..."):
            st.session_state.qa_history.append({"question": prompt, "answer": "..."})
            with st.spinner("Analizando..."):
                ans = answer_question(prompt, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history[:-1])
                st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Nuevo Archivo"):
        st.session_state.clear()
        st.rerun()
