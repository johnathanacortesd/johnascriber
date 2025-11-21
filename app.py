import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import math
import streamlit.components.v1 as components
from datetime import timedelta

# Importar MoviePy para manejo robusto de audio y video
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

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
        <h2>Transcriptor Pro - Johnascriptor</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- API KEY ---
try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- ESTADO INICIAL ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback(): st.session_state.search_input = ""
def clear_brands_search_callback(): st.session_state.brands_search = ""

# --- UTILIDADES DE TEXTO Y CODIFICACIÓN ---
def fix_spanish_encoding(text):
    """Corrige errores comunes de codificación UTF-8 mal interpretada."""
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
        'Ã': 'í', 'Ã“': 'Ó', 'ÃNQ': 'Ñ', 'Â': '', 'â': ''
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.strip()

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def export_to_srt(segments):
    srt_content = []
    for i, seg in enumerate(segments, 1):
        start = timedelta(seconds=seg['start'])
        end = timedelta(seconds=seg['end'])
        # Formato SRT: HH:MM:SS,mmm
        s_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        e_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt_content.append(f"{i}\n{s_str} --> {e_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-{hash(text_to_copy)}"
    html = f"""<button id="{button_id}" style="width:100%;padding:0.5rem;border-radius:5px;border:1px solid #ccc;background:#fff;cursor:pointer;">📋 Copiar Todo</button>
    <script>
    document.getElementById("{button_id}").onclick = function() {{
        const el = document.createElement('textarea'); el.value = {text_json}; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el);
        const btn = document.getElementById("{button_id}"); btn.innerText = "✅ ¡Copiado!"; setTimeout(()=>btn.innerText="📋 Copiar Todo", 2000);
    }};
    </script>"""
    components.html(html, height=40)

# --- MOTOR DE AUDIO (MOVIEPY) ---
def convert_and_optimize_audio(file_bytes, file_ext):
    """Convierte cualquier entrada a MP3 Mono 16kHz para Whisper."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name
        
        output_path = input_path + "_opt.mp3"
        
        # Cargar audio
        audio_clip = AudioFileClip(input_path)
        
        # Escribir optimizado (Mono, 16k Hz, 64k bitrate)
        audio_clip.write_audiofile(
            output_path, fps=16000, nbytes=2, codec='libmp3lame', bitrate='64k',
            ffmpeg_params=["-ac", "1"], verbose=False, logger=None
        )
        audio_clip.close()
        
        with open(output_path, 'rb') as f:
            optimized_bytes = f.read()
            
        # Limpieza
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        
        return optimized_bytes, True
    except Exception as e:
        print(f"Error conversión: {e}")
        return file_bytes, False

# --- LÓGICA CORE: TRANSCRIPCIÓN POR CHUNKS (LA SOLUCIÓN AL CORTE) ---
def transcribe_audio_chunked(file_bytes, client, model, language, chunk_minutes=10):
    """
    Divide el audio en segmentos, transcribe cada uno y une los resultados.
    Maneja los timestamps para que sean continuos.
    """
    # 1. Guardar bytes en archivo temporal
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        tmp_file.write(file_bytes)
        audio_path = tmp_file.name

    full_text = ""
    all_segments = []
    
    try:
        clip = AudioFileClip(audio_path)
        duration = clip.duration
        chunk_duration = chunk_minutes * 60
        
        total_chunks = math.ceil(duration / chunk_duration)
        progress_bar = st.progress(0)
        
        for i in range(total_chunks):
            start_time = i * chunk_duration
            end_time = min((i + 1) * chunk_duration, duration)
            
            # Crear subclip
            subclip = clip.subclip(start_time, end_time)
            chunk_name = f"{audio_path}_chunk_{i}.mp3"
            
            # Exportar chunk temporalmente
            subclip.write_audiofile(chunk_name, fps=16000, bitrate='64k', verbose=False, logger=None)
            
            # Transcribir Chunk
            with open(chunk_name, "rb") as audio_chunk:
                transcription = client.audio.transcriptions.create(
                    file=(f"chunk_{i}.mp3", audio_chunk.read()),
                    model=model,
                    language=language,
                    response_format="verbose_json",
                    temperature=0.0, # Determinista
                    prompt="Transcripción en español completa. Mantener tildes y puntuación exacta. No resumir."
                )
            
            # Procesar resultados del chunk
            chunk_text = fix_spanish_encoding(transcription.text)
            full_text += chunk_text + " "
            
            # Ajustar timestamps y agregar segmentos
            if hasattr(transcription, 'segments'):
                for seg in transcription.segments:
                    seg['start'] += start_time
                    seg['end'] += start_time
                    seg['text'] = fix_spanish_encoding(seg['text'])
                    all_segments.append(seg)
            
            # Limpieza chunk
            subclip.close()
            if os.path.exists(chunk_name): os.unlink(chunk_name)
            
            # Actualizar progreso UI
            progress_bar.progress((i + 1) / total_chunks, text=f"Transcribiendo segmento {i+1}/{total_chunks}...")

        clip.close()
        progress_bar.empty()
        
    except Exception as e:
        if os.path.exists(audio_path): os.unlink(audio_path)
        raise e
    
    if os.path.exists(audio_path): os.unlink(audio_path)
    
    return full_text.strip(), all_segments

# --- LÓGICA CORE: CORRECCIÓN ORTOGRÁFICA CHUNKEADA ---
def chunked_spell_check(text, client):
    """
    Corrección ortográfica segura para textos largos.
    Divide el texto en bloques de ~2000 caracteres para evitar que Llama corte el final.
    """
    # Dividir texto en chunks aproximados
    chunk_size = 2000
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    corrected_full_text = []
    
    progress_text = st.empty()
    
    for idx, chunk in enumerate(chunks):
        progress_text.text(f"✨ Puliendo ortografía: bloque {idx+1}/{len(chunks)}...")
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres un corrector ortográfico estricto en español. Tu ÚNICA tarea es corregir tildes, signos de puntuación y errores gramaticales evidentes. \nREGLAS:\n1. NO resumas.\n2. NO elimines texto.\n3. Devuelve EL MISMO TEXTO exactamente, solo corrigiendo la ortografía.\n4. Si el texto está cortado al final, déjalo como está."},
                    {"role": "user", "content": f"Corrige este texto:\n\n{chunk}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.1,
                max_tokens=1500
            )
            corrected_full_text.append(response.choices[0].message.content)
        except Exception:
            corrected_full_text.append(chunk) # Si falla, usar original
            
    progress_text.empty()
    return "".join(corrected_full_text)

# --- FUNCIONES DE ANÁLISIS (RESUMEN, ENTIDADES) ---
def generate_summary(text, client):
    if len(text) > 15000: text = text[:15000] # Limitar contexto para resumen
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un experto redactor de noticias. Genera un resumen ejecutivo estructurado en español."},
                {"role": "user", "content": f"Resume el siguiente texto en máximo 200 palabras:\n\n{text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception: return "No se pudo generar el resumen."

def extract_entities(text, client, entity_type):
    # entity_type: "personas" o "marcas"
    prompt_map = {
        "personas": 'Extrae nombres de personas y sus cargos. JSON: { "items": [{"name": "Nombre", "role": "Cargo", "context": "Frase clave"}] }',
        "marcas": 'Extrae empresas, marcas e instituciones. JSON: { "items": [{"name": "Entidad", "type": "Tipo", "context": "Frase clave"}] }'
    }
    # Tomamos una muestra representativa si es muy largo para evitar timeout
    sample_text = text[:6000] 
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"Analista de datos. {prompt_map[entity_type]}. Devuelve JSON válido. Si no hay, array vacío."},
                {"role": "user", "content": f"Texto:\n{sample_text}"}
            ],
            model="llama-3.1-8b-instant", response_format={"type": "json_object"}, temperature=0.0
        )
        data = json.loads(completion.choices[0].message.content)
        return data.get("items", [])
    except Exception: return []

def answer_question(question, text, client, history):
    messages = [{"role": "system", "content": "Responde preguntas sobre el texto proporcionado en español."}]
    for h in history:
        messages.append({"role": "user", "content": h['question']})
        messages.append({"role": "assistant", "content": h['answer']})
    
    # Contexto dinámico (últimos 10k caracteres si es muy largo)
    context = text if len(text) < 10000 else text[:10000]
    messages.append({"role": "user", "content": f"Contexto:\n{context}\n\nPregunta: {question}"})
    
    try:
        resp = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant")
        return resp.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

# --- UI: BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Configuración")
    st.success("🚀 **Modo Full-Audio Activo**\nEl sistema divide y procesa el audio en bloques para evitar cortes.")
    
    enable_spellcheck = st.checkbox("✨ Corrección Ortográfica IA", value=True, help="Tarda un poco más, pero asegura tildes perfectas.")
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_entities = st.checkbox("🔍 Extraer Datos (Personas/Marcas)", value=True)
    
    st.divider()
    st.info(f"Motor de Audio: {'✅ MoviePy Activo' if MOVIEPY_AVAILABLE else '⚠️ Modo Básico'}")

# --- UI: PRINCIPAL ---
st.subheader("📤 Sube tu archivo (Audio/Video)")
uploaded_file = st.file_uploader("Soporta MP3, MP4, M4A, WAV, etc.", type=None)

if st.button("🚀 Iniciar Transcripción Completa", type="primary", disabled=not uploaded_file):
    if not MOVIEPY_AVAILABLE:
        st.error("❌ Se requiere la librería 'moviepy' instalada para la función de segmentación.")
        st.stop()

    # Reset variables
    st.session_state.qa_history = []
    st.session_state.brands_search = ""
    st.session_state.search_input = ""
    
    client = Groq(api_key=api_key)
    
    try:
        # 1. Optimización de Audio
        with st.spinner("🔄 1/4 Preparando motor de audio..."):
            file_bytes = uploaded_file.getvalue()
            file_ext = os.path.splitext(uploaded_file.name)[1]
            optimized_bytes, converted = convert_and_optimize_audio(file_bytes, file_ext)
            st.session_state.uploaded_audio_bytes = optimized_bytes # Guardar para reproductor

        # 2. Transcripción Robusta (Chunking)
        st.info("🔄 2/4 Transcribiendo audio completo (esto asegura que no se corte)...")
        full_text, segments = transcribe_audio_chunked(
            optimized_bytes, client, "whisper-large-v3", "es"
        )

        # 3. Corrección Ortográfica Segura
        if enable_spellcheck:
            full_text = chunked_spell_check(full_text, client)
            # Actualizar texto en segmentos (básico, para búsqueda)
            # Nota: Alinear segmentos con texto corregido es complejo, 
            # mantenemos segmentos "raw" para tiempos y texto "full" corregido.

        st.session_state.transcription_text = full_text
        st.session_state.segments = segments
        
        # 4. Análisis IA
        with st.spinner("🧠 4/4 Analizando contenido..."):
            if enable_summary:
                st.session_state.summary = generate_summary(full_text, client)
            if enable_entities:
                st.session_state.people = extract_entities(full_text, client, "personas")
                st.session_state.brands = extract_entities(full_text, client, "marcas")

        st.success("✅ ¡Proceso terminado con éxito!")
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error crítico: {str(e)}")

# --- UI: RESULTADOS ---
if 'transcription_text' in st.session_state:
    st.divider()
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📄 Transcripción", "📊 Resumen & Chat", "👥 Personas", "🏢 Marcas"])
    
    # --- PESTAÑA 1: TRANSCRIPCIÓN ---
    with tabs[0]:
        col_s1, col_s2 = st.columns([4, 1])
        with col_s1: search_q = st.text_input("🔎 Buscar:", key="search_input")
        with col_s2: 
            st.write("")
            st.button("Limpiar", on_click=clear_search_callback)

        # Resultados de búsqueda con contexto temporal
        if search_q:
            found_count = 0
            st.markdown("### 📍 Coincidencias en el tiempo")
            for seg in st.session_state.segments:
                if search_q.lower() in seg['text'].lower():
                    found_count += 1
                    time_str = format_timestamp(seg['start'])
                    
                    c1, c2 = st.columns([0.15, 0.85])
                    with c1:
                        st.button(f"▶️ {time_str}", key=f"btn_{seg['start']}", on_click=set_audio_time, args=(seg['start'],))
                    with c2:
                        highlighted = re.sub(f"({re.escape(search_q)})", r"<mark style='background:#fca311;color:black'>\1</mark>", seg['text'], flags=re.IGNORECASE)
                        st.markdown(f"<div style='background:#262730;padding:5px;border-radius:5px'>{highlighted}</div>", unsafe_allow_html=True)
            
            if found_count == 0: st.warning("No se encontraron coincidencias.")
            st.divider()

        # Texto completo
        st.markdown("### 📝 Texto Completo")
        display_html = st.session_state.transcription_text.replace("\n", "<br>")
        if search_q:
            display_html = re.sub(f"({re.escape(search_q)})", r"<mark style='background:#fca311;color:black'>\1</mark>", display_html, flags=re.IGNORECASE)
            
        st.markdown(
            f"<div style='height:400px;overflow-y:scroll;background:#0E1117;padding:15px;border:1px solid #333;border-radius:5px;'>{display_html}</div>", 
            unsafe_allow_html=True
        )
        
        # Descargas
        st.write("")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.download_button("💾 TXT", st.session_state.transcription_text, "transcripcion.txt", use_container_width=True)
        with c2: st.download_button("💾 SRT (Subtítulos)", export_to_srt(st.session_state.segments), "subtitulos.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription_text)

    # --- PESTAÑA 2: CHAT & RESUMEN ---
    with tabs[1]:
        if 'summary' in st.session_state:
            st.info(st.session_state.summary)
        
        st.divider()
        st.markdown("### 💬 Chat con el Audio")
        
        for msg in st.session_state.qa_history:
            with st.chat_message("user"): st.write(msg['question'])
            with st.chat_message("assistant"): st.write(msg['answer'])
            
        if prompt := st.chat_input("Pregunta algo sobre el audio..."):
            with st.chat_message("user"): st.write(prompt)
            with st.spinner("Pensando..."):
                ans = answer_question(prompt, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history)
            with st.chat_message("assistant"): st.write(ans)
            st.session_state.qa_history.append({"question": prompt, "answer": ans})

    # --- PESTAÑA 3: PERSONAS ---
    with tabs[2]:
        if 'people' in st.session_state:
            for p in st.session_state.people:
                st.markdown(f"👤 **{p.get('name', '?')}** - *{p.get('role', 'Rol desconocido')}*")
                st.caption(f"Contexto: {p.get('context', '')}")
                st.divider()

    # --- PESTAÑA 4: MARCAS ---
    with tabs[3]:
        if 'brands' in st.session_state:
            bq = st.text_input("Filtrar marcas:", key="brands_search")
            items = st.session_state.brands
            if bq: items = [i for i in items if bq.lower() in i.get('name','').lower()]
            
            for b in items:
                st.markdown(f"🏢 **{b.get('name', '?')}** ({b.get('type', 'Entidad')})")
                st.caption(f"Contexto: {b.get('context', '')}")
