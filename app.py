import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta

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
        <h2>Transcriptor Pro - Edición Exacta</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Sin resúmenes, sin inventos. Solo tu texto y chat.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro V11", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# --- CALLBACKS UI (CRUCIAL PARA TIMESTAMPS) ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

# --- FUNCIONES DE LIMPIEZA (ANTI-ALUCINACIONES) ---
def clean_whisper_hallucinations(text):
    """Limpia frases inventadas comunes en silencios y bucles."""
    if not text: return ""
    
    # Patrones de basura que Whisper V3 suele inventar
    junk_patterns = [
        r"Subtítulos realizados por.*",
        r"Comunidad de editores.*",
        r"Amara\.org.*",
        r"Transcribed by.*",
        r"Sujeto a.*licencia.*",
        r"Copyright.*",
        r"Gracias por ver.*",
        r"Suscríbete.*"
    ]
    
    cleaned = text
    for pattern in junk_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Eliminar repeticiones Bucle (ej: "hola hola hola")
    cleaned = re.sub(r'\b(\w+)( \1\b)+', r'\1', cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()

def filter_segments_data(segments):
    """Limpia la data de segmentos para que los timestamps no apunten a basura."""
    clean_segments = []
    last_text = ""
    
    for seg in segments:
        txt = clean_whisper_hallucinations(seg['text'])
        
        # Filtros de calidad
        if len(txt) < 2: continue # Muy corto
        if txt.lower() == last_text.lower(): continue # Repetido
        
        seg['text'] = txt # Actualizamos el texto limpio
        clean_segments.append(seg)
        last_text = txt
        
    return clean_segments

# --- FUNCIONES DE CORRECCIÓN QUIRÚRGICA ---
def text_chunker_smart(text, chunk_size=2500):
    """Corta por oraciones para no romper contexto."""
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
    """
    Corrección estricta: solo tildes. 
    Safety Check: Si cambia mucho el texto (longitud), se descarta el cambio.
    """
    chunks = text_chunker_smart(text)
    final_parts = []
    
    progress_text = "🧠 Aplicando corrección quirúrgica (solo tildes)..."
    my_bar = st.progress(0, text=progress_text)
    
    system_prompt = """Eres un corrector ortográfico estricto.
TU ÚNICA MISIÓN: Poner tildes faltantes en español.
PROHIBIDO:
- Cambiar palabras (ej: 'telefono' -> 'móvil' PROHIBIDO).
- Resumir.
- Eliminar texto.
- Cambiar puntuación técnica.

Entrada: "la telefonia y la tecnologia"
Salida: "la telefonía y la tecnología"

Si la entrada ya está bien, devuélvela IDÉNTICA. Solo responde con el texto corregido."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant",
                temperature=0.0, # Determinístico
                max_tokens=len(chunk) + 500
            )
            corrected = response.choices[0].message.content.strip()
            
            # --- SAFETY CHECK ---
            # Si la longitud cambia más de un 10%, el modelo alucinó/resumió. Descartar.
            len_diff = abs(len(corrected) - len(chunk))
            ratio = len_diff / len(chunk) if len(chunk) > 0 else 0
            
            if ratio > 0.10: 
                # Fallback al original si el cambio es sospechoso
                final_parts.append(chunk)
            else:
                final_parts.append(corrected)
                
        except:
            final_parts.append(chunk)
            
        my_bar.progress((i + 1) / len(chunks))
        
    my_bar.empty()
    return " ".join(final_parts)

# --- UTILIDADES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #ddd; background: #fff;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
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

# --- OPTIMIZACIÓN AUDIO (FFMPEG) ---
def optimize_audio_robust(file_bytes, filename):
    """
    Convierte cualquier entrada a MP3 16kHz Mono 32kbps.
    Esto es CRUCIAL para que Whisper no alucine.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp.write(file_bytes)
        input_path = tmp.name
    
    output_path = input_path + "_opt.mp3"
    try:
        # Comando optimizado para voz
        subprocess.run(["ffmpeg", "-y", "-i", input_path, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", "-f", "mp3", output_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(output_path, 'rb') as f: new_bytes = f.read()
        os.unlink(input_path); os.unlink(output_path)
        return new_bytes, True
    except:
        # Si falla ffmpeg, usamos el original pero advertimos
        if os.path.exists(input_path): os.unlink(input_path)
        return file_bytes, False

# --- FUNCIÓN CHAT ---
def answer_question(q, text, client, history):
    msgs = [{"role": "system", "content": "Eres un asistente útil. Responde preguntas basándote ÚNICAMENTE en la transcripción proporcionada. Si no está en el texto, dilo."}]
    for item in history:
        msgs.append({"role": "user", "content": item['question']})
        msgs.append({"role": "assistant", "content": item['answer']})
    msgs.append({"role": "user", "content": f"Transcripción:\n{text[:25000]}\n\nPregunta: {q}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    st.markdown("### Modos de Precisión")
    mode = st.radio("Nivel de Corrección:", ["Whisper Puro (Sin cambios)", "Quirúrgico (Solo Tildes)"], index=1)
    st.markdown("---")
    st.info("✅ Optimización FFmpeg activa para cada archivo.")

uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov"])

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    try:
        # 1. OPTIMIZAR (SIEMPRE SE EJECUTA)
        with st.spinner("🔄 Optimizando audio con FFmpeg (16kHz Mono)..."):
            audio_bytes, optimized = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = audio_bytes
            if not optimized: st.warning("⚠️ No se pudo optimizar el audio, usando original.")

        # 2. TRANSCRIBIR (WHISPER)
        with st.spinner("📝 Transcribiendo (Modo Exacto)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            with open(tmp_path, "rb") as f:
                # Temperature 0.0 + Prompt específico para reducir alucinaciones
                transcription_data = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0, 
                    prompt="Transcripción literal. Sin repetir. Español."
                )
            os.unlink(tmp_path)

        # 3. LIMPIEZA ANTI-ALUCINACIONES
        raw_text_cleaned = clean_whisper_hallucinations(transcription_data.text)
        segments_cleaned = filter_segments_data(transcription_data.segments)
        
        # 4. CORRECCIÓN (OPCIONAL PERO RECOMENDADA)
        if mode == "Quirúrgico (Solo Tildes)":
            final_text = surgical_correction(raw_text_cleaned, client)
        else:
            final_text = raw_text_cleaned
            
        # 5. ACTUALIZAR ESTADO
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
    
    tab1, tab2 = st.tabs(["📝 Transcripción & Búsqueda", "💬 Chat con Audio"])
    
    # --- TAB 1: TRANSCRIPCIÓN INTERACTIVA ---
    with tab1:
        col_s1, col_s2 = st.columns([4, 1])
        query = col_s1.text_input("🔎 Buscar palabra (Clic en resultados para ir al audio):", key="search_input")
        col_s2.write(""); col_s2.button("✖️", on_click=clear_search_callback)
        
        # BÚSQUEDA Y RESULTADOS CLICABLES
        if query:
            matches_found = False
            with st.expander(f"📍 Resultados para: '{query}'", expanded=True):
                # Usamos los segmentos limpios para buscar
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        matches_found = True
                        # Mostrar contexto
                        context = get_extended_context(st.session_state.segments, i, 1)
                        for ctx in context:
                            c1, c2 = st.columns([0.15, 0.85])
                            # EL BOTÓN MÁGICO PARA IR AL TIEMPO
                            key_btn = f"t_{i}_{ctx['start']}"
                            c1.button(f"▶️ {ctx['time']}", key=key_btn, on_click=set_audio_time, args=(ctx['start'],))
                            
                            # Resaltado
                            txt_display = ctx['text']
                            if ctx['is_match']:
                                txt_display = re.sub(re.escape(query), f"**{query.upper()}**", txt_display, flags=re.IGNORECASE)
                            c2.markdown(txt_display)
                        st.divider()
                if not matches_found: st.warning("No se encontraron coincidencias.")

        st.markdown("### 📄 Texto Completo")
        st.text_area("Copia el texto aquí:", st.session_state.transcription_text, height=600, label_visibility="collapsed")
        
        c1, c2, c3 = st.columns([1,1,1])
        c1.download_button("💾 TXT", st.session_state.transcription_text, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 SRT (Subtítulos)", export_to_srt(st.session_state.segments), "subs.srt", use_container_width=True)
        with c3: create_copy_button(st.session_state.transcription_text)

    # --- TAB 2: CHAT ---
    with tab2:
        st.subheader("💬 Chat con el Audio")
        st.caption("Haz preguntas específicas sobre la transcripción.")
        
        for msg in st.session_state.qa_history:
            with st.chat_message("user"): st.write(msg['question'])
            with st.chat_message("assistant"): st.write(msg['answer'])
            
        if prompt := st.chat_input("Pregunta algo sobre el contenido..."):
            st.session_state.qa_history.append({"question": prompt, "answer": "..."})
            with st.spinner("Consultando transcripción..."):
                ans = answer_question(prompt, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history[:-1])
                st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo / Nuevo Archivo"):
        st.session_state.clear()
        st.rerun()
