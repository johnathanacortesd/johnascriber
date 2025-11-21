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
        <h2>Transcriptor Pro - Johnascriptor</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Versión Estable - Audio Optimizado</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro - V7", page_icon="🎙️", layout="wide")

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

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â\u00bf': '¿', 'Â\u00a1': '¡'
    }
    for wrong, correct in replacements.items():
        result = result.replace(wrong, correct)
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', lambda m: m.group(1) + m.group(2).upper(), result)
    return result.strip()

# --- LIMPIEZA POR TROZOS (ANTI-CORTES) ---
def text_chunker(text, chunk_size=2500):
    chunks = []
    current_chunk = ""
    sentences = re.split(r'(?<=[.?!])\s+', text)
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def post_process_with_llama_chunked(transcription_text, client):
    chunks = text_chunker(transcription_text)
    cleaned_chunks = []
    
    progress_text = "🧠 IA corrigiendo ortografía y tildes..."
    my_bar = st.progress(0, text=progress_text)
    total_chunks = len(chunks)

    system_prompt = """Eres un corrector ortográfico experto en español. 
    TU TAREA: Corregir tildes y puntuación.
    REGLAS: 1. NO resumas. 2. NO cortes el texto. 3. Devuelve SOLO el texto corregido."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Corregir:\n\n{chunk}"}
                ],
                model="llama-3.1-8b-instant", 
                temperature=0.1,
                max_tokens=len(chunk) + 500 
            )
            corrected = response.choices[0].message.content.strip()
            cleaned_chunks.append(corrected)
        except Exception:
            cleaned_chunks.append(chunk)
        
        my_bar.progress((i + 1) / total_chunks, text=f"{progress_text} ({i+1}/{total_chunks})")

    my_bar.empty()
    return " ".join(cleaned_chunks)

# --- OPTIMIZACIÓN ROBUSTA (FFMPEG) ---
def optimize_audio_robust(file_bytes, filename):
    file_ext = os.path.splitext(filename)[1]
    if not file_ext: file_ext = ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path + "_opt.mp3"
    original_size = len(file_bytes) / (1024 * 1024)
    
    try:
        command = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k",
            "-f", "mp3", output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, 'rb') as f:
                new_bytes = f.read()
            
            final_size = len(new_bytes) / (1024 * 1024)
            os.unlink(input_path); os.unlink(output_path)
            
            reduction = ((original_size - final_size) / original_size * 100) if original_size > 0 else 0
            return new_bytes, {'converted': True, 'message': f"✅ Optimizado: {original_size:.1f}MB → {final_size:.1f}MB (-{reduction:.0f}%)"}
        else:
            raise Exception("Falló conversión FFmpeg")

    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, {'converted': False, 'message': f"⚠️ Usando original. Error: {str(e)}"}

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto. Resumen ejecutivo en español, un solo párrafo."},
                {"role": "user", "content": f"Resume esto:\n\n{transcription_text[:15000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Texto:\n{transcription_text[:25000]}\n\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    return [{'text': segments[i]['text'].strip(), 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start_idx, end_idx)]

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start = timedelta(seconds=seg['start'])
        end = timedelta(seconds=seg['end'])
        s_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        e_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt_content.append(f"{i}\n{s_str} --> {e_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    enable_llama_postprocess = st.checkbox("🤖 Corrección Ortográfica IA", value=True)
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    st.markdown("---")
    context_lines = st.slider("Líneas de contexto búsqueda", 1, 5, 2)
    st.info("✅ Motor FFmpeg: MP3 Mono 32kbps activo.")

st.subheader("📤 Sube tu archivo (Audio/Video)")
uploaded_file = st.file_uploader("Selecciona archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mov", "avi"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    try:
        # 1. OPTIMIZACIÓN
        with st.spinner("🔄 Comprimiendo audio con FFmpeg..."):
            file_bytes, conversion_info = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = file_bytes
            if conversion_info['converted']:
                st.success(conversion_info['message'])
            else:
                st.warning(conversion_info['message'])

        client = Groq(api_key=api_key)
        
        # 2. TRANSCRIPCIÓN
        with st.spinner("🔄 Transcribiendo con Whisper V3..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_file.read()), 
                    model="whisper-large-v3", 
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0,
                    prompt="Transcripción en español latino. Tildes correctas en: qué, cómo, cuándo, dónde, público, político, administración."
                )
            os.unlink(tmp_path)
            
        transcription_text = fix_spanish_encoding(transcription.text)
        
        # 3. POST-PROCESAMIENTO
        if enable_llama_postprocess:
            transcription_text = post_process_with_llama_chunked(transcription_text, client)
        
        for seg in transcription.segments:
            seg['text'] = fix_spanish_encoding(seg['text'])

        st.session_state.transcription = transcription_text
        st.session_state.transcription_data = transcription
        
        if enable_summary:
            with st.spinner("📝 Generando resumen..."):
                st.session_state.summary = generate_summary(transcription_text, client)
        
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error crítico: {e}")

# --- VISUALIZACIÓN ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproductor")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📝 Transcripción Completa", "📊 Resumen y Chat"])
    
    # --- TAB 1: TRANSCRIPCIÓN ---
    with tab1:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        col1, col2 = st.columns([4, 1])
        search_query = col1.text_input("🔎 Buscar en texto:", key="search_input")
        col2.write(""); col2.button("🗑️", on_click=clear_search_callback)

        # BÚSQUEDA CON KEY ÚNICO SOLUCIONADO
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if matches:
                    for idx_match, i in enumerate(matches):
                        for idx_ctx, ctx in enumerate(get_extended_context(segments, i, context_lines)):
                            c_t, c_txt = st.columns([0.15, 0.85])
                            # Key único compuesto para evitar DuplicateWidgetID
                            btn_key = f"play_{idx_match}_{idx_ctx}_{ctx['start']}"
                            c_t.button(f"▶️ {ctx['time']}", key=btn_key, on_click=set_audio_time, args=(ctx['start'],))
                            
                            txt_show = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx['text']) if ctx['is_match'] else ctx['text']
                            c_txt.markdown(txt_show, unsafe_allow_html=True)
                        st.divider()
                else: st.info("Sin coincidencias.")

        st.markdown("### 📄 Texto Transcrito")
        
        # --- AQUÍ ESTÁ EL ESTILO NEGRO SOLICITADO ---
        html_text = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            html_text = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', html_text)
        
        st.markdown(f"""
        <div style="
            background-color: #000000; 
            color: #FFFFFF; 
            padding: 20px; 
            border-radius: 10px; 
            border: 1px solid #333; 
            font-family: sans-serif; 
            line-height: 1.6; 
            max-height: 600px; 
            overflow-y: auto;
            white-space: pre-wrap;">
            {html_text}
        </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2,2,2,1.5])
        c1.download_button("💾 Descargar TXT", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 Descargar Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "tiempos.txt", use_container_width=True)
        c3.download_button("💾 Descargar SRT", export_to_srt(st.session_state.transcription_data), "subs.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    # --- TAB 2: RESUMEN Y CHAT ---
    with tab2:
        if 'summary' in st.session_state:
            st.markdown(f"### 📝 Resumen Ejecutivo\n{st.session_state.summary}")
            st.divider()
            
            st.markdown("### 💬 Chat con el Audio")
            for qa in st.session_state.qa_history:
                st.markdown(f"**Q:** {qa['question']}")
                st.markdown(f"**A:** {qa['answer']}")
                st.divider()
            
            with st.form("chat_form"):
                q = st.text_area("Haz una pregunta sobre el contenido:")
                if st.form_submit_button("Preguntar") and q:
                    with st.spinner("Pensando..."):
                        ans = answer_question(q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': q, 'answer': ans})
                        st.rerun()
        else: st.info("Resumen no generado. Habilita la opción en el menú.")
    
    st.markdown("---")
    if st.button("🗑️ Empezar de nuevo (Limpiar todo)"):
        st.session_state.clear()
        st.rerun()
