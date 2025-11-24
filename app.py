import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
import glob

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
        <h2>Transcriptor Pro - Ultimate V12</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Segmentación Inteligente: No se pierde ni un segundo.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro V12", page_icon="🎙️", layout="wide")

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

# --- FUNCIONES DE LIMPIEZA ---
def clean_whisper_hallucinations(text):
    if not text: return ""
    junk_patterns = [
        r"Subtítulos realizados por.*", r"Comunidad de editores.*", r"Amara\.org.*",
        r"Transcribed by.*", r"Sujeto a.*licencia.*", r"Copyright.*", 
        r"Gracias por ver.*", r"Suscríbete.*", r"Editado por.*"
    ]
    cleaned = text
    for pattern in junk_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(\w+)( \1\b)+', r'\1', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def filter_segments_data(segments):
    clean_segments = []
    last_text = ""
    for seg in segments:
        txt = clean_whisper_hallucinations(seg['text'])
        if len(txt) < 2: continue 
        if txt.lower() == last_text.lower(): continue 
        seg['text'] = txt 
        clean_segments.append(seg)
        last_text = txt
    return clean_segments

# --- CORRECCIÓN QUIRÚRGICA ---
def text_chunker_smart(text, chunk_size=2500):
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
    progress_text = "🧠 Aplicando corrección quirúrgica (solo tildes)..."
    my_bar = st.progress(0, text=progress_text)
    
    system_prompt = "Eres un corrector ortográfico estricto. TU TAREA: Poner tildes faltantes. PROHIBIDO cambiar palabras, resumir o eliminar texto. Si está bien, devuélvelo IDÉNTICO."

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant", temperature=0.0, max_tokens=len(chunk) + 500
            )
            corrected = response.choices[0].message.content.strip()
            # Safety Check: Si la longitud cambia >10%, usamos el original
            if abs(len(corrected) - len(chunk)) / len(chunk) > 0.10: 
                final_parts.append(chunk)
            else:
                final_parts.append(corrected)
        except:
            final_parts.append(chunk)
        my_bar.progress((i + 1) / len(chunks))
    my_bar.empty()
    return " ".join(final_parts)

# --- UTILIDADES DE ARCHIVO Y FFMPEG ---
def optimize_and_split_audio(file_bytes, filename, segment_time=600):
    """
    1. Optimiza a 16kHz Mono (Whisper friendly).
    2. Si es largo, lo corta en pedazos de 10 mins (600s) para evitar límites de API.
    Retorna: lista de rutas de archivos chunks, y el path del archivo completo optimizado.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    
    # Directorio temporal único
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, f"original{file_ext}")
    
    with open(input_path, "wb") as f:
        f.write(file_bytes)

    optimized_path = os.path.join(temp_dir, "full_optimized.mp3")
    
    try:
        # Paso 1: Optimización General (Aumenté bitrate a 64k para mayor claridad)
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path, 
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", 
            "-f", "mp3", optimized_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Paso 2: Segmentación (Chunking)
        # Corta en archivos part000.mp3, part001.mp3, etc.
        chunk_pattern = os.path.join(temp_dir, "part%03d.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-i", optimized_path,
            "-f", "segment", "-segment_time", str(segment_time),
            "-c", "copy", "-reset_timestamps", "1",
            chunk_pattern
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        chunks = sorted(glob.glob(os.path.join(temp_dir, "part*.mp3")))
        
        # Leemos el archivo completo optimizado para el reproductor
        with open(optimized_path, 'rb') as f:
            full_audio_bytes = f.read()
            
        return chunks, full_audio_bytes, temp_dir
        
    except Exception as e:
        # Fallback: devolver solo el original si falla ffmpeg
        return [input_path], file_bytes, temp_dir

# --- INTERFAZ UTILIDADES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; background: #fff;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
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
    msgs.append({"role": "user", "content": f"Transcripción:\n{text[:25000]}\n\nPregunta: {q}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- MAIN ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    mode = st.radio("Nivel de Corrección:", ["Whisper Puro (Sin cambios)", "Quirúrgico (Solo Tildes)"], index=1)
    st.info("✅ Sistema Splitter activo: Procesa archivos de cualquier duración sin cortes.")

uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov"])

if st.button("🚀 Iniciar Transcripción Segura", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    try:
        # 1. OPTIMIZACIÓN Y SPLIT
        with st.spinner("🔄 Procesando: Optimizando y dividiendo audio en segmentos seguros..."):
            # Dividimos en chunks de 10 min (600s) para garantizar que Groq no corte el audio
            chunks, full_audio, temp_dir = optimize_and_split_audio(uploaded_file.getvalue(), uploaded_file.name, segment_time=600)
            st.session_state.uploaded_audio_bytes = full_audio
        
        all_segments = []
        full_text_accumulated = ""
        
        # 2. TRANSCRIPCIÓN ITERATIVA
        progress_bar = st.progress(0, text="📝 Transcribiendo segmentos...")
        
        for i, chunk_path in enumerate(chunks):
            # Calcular offset de tiempo (ej: chunk 2 empieza en 600s)
            time_offset = i * 600 
            
            with open(chunk_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0, # Máxima fidelidad
                    prompt="Transcripción literal exacta. Español."
                )
            
            # Limpiar alucinaciones del chunk
            cleaned_text = clean_whisper_hallucinations(transcription.text)
            full_text_accumulated += cleaned_text + " "
            
            # Ajustar timestamps y agregar segmentos
            for seg in transcription.segments:
                seg['start'] += time_offset
                seg['end'] += time_offset
                # Filtro de segmentos basura
                txt_seg = clean_whisper_hallucinations(seg['text'])
                if len(txt_seg) > 1:
                    seg['text'] = txt_seg
                    all_segments.append(seg)
            
            progress_bar.progress((i + 1) / len(chunks))
            
        progress_bar.empty()
        
        # Limpieza de temporales
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

        # 3. CORRECCIÓN
        if mode == "Quirúrgico (Solo Tildes)":
            final_text = surgical_correction(full_text_accumulated, client)
        else:
            final_text = full_text_accumulated
            
        st.session_state.transcription_text = final_text
        st.session_state.segments = all_segments
        
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error durante el proceso: {e}")

# --- VISUALIZACIÓN ---
if 'transcription_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📝 Transcripción & Búsqueda", "💬 Chat con Audio"])
    
    with tab1:
        col_s1, col_s2 = st.columns([4, 1])
        query = col_s1.text_input("🔎 Buscar palabra:", key="search_input")
        col_s2.write(""); col_s2.button("✖️", on_click=clear_search_callback)
        
        if query:
            matches_found = False
            with st.expander(f"📍 Resultados para: '{query}'", expanded=True):
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        matches_found = True
                        context = get_extended_context(st.session_state.segments, i, 1)
                        for ctx in context:
                            c1, c2 = st.columns([0.15, 0.85])
                            key_btn = f"t_{i}_{ctx['start']}"
                            c1.button(f"▶️ {ctx['time']}", key=key_btn, on_click=set_audio_time, args=(ctx['start'],))
                            
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
        c2.download_button("💾 SRT", export_to_srt(st.session_state.segments), "subs.srt", use_container_width=True)
        with c3: create_copy_button(st.session_state.transcription_text)

    with tab2:
        st.subheader("💬 Chat con el Audio")
        for msg in st.session_state.qa_history:
            with st.chat_message("user"): st.write(msg['question'])
            with st.chat_message("assistant"): st.write(msg['answer'])
            
        if prompt := st.chat_input("Pregunta algo sobre el contenido..."):
            st.session_state.qa_history.append({"question": prompt, "answer": "..."})
            with st.spinner("Consultando..."):
                ans = answer_question(prompt, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history[:-1])
                st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo"):
        st.session_state.clear()
        st.rerun()
