import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import math
import streamlit.components.v1 as components
from datetime import timedelta

# Importar para conversión de audio
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
        <h2>Transcriptor Pro - Johnascriptor V2.1</h2>
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

# --- ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []
if 'brands_search' not in st.session_state:
    st.session_state.brands_search = ""

# --- CALLBACKS (CORREGIDOS) ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    # Esta función se ejecutará ANTES de renderizar los widgets al hacer clic
    st.session_state.search_input = ""

def clear_brands_search_callback():
    st.session_state.brands_search = ""

# --- API KEY ---
try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- UTILIDADES DE TEXTO ---
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

def export_to_srt(segments):
    srt_content = []
    for i, seg in enumerate(segments, 1):
        start_time = timedelta(seconds=seg['start'])
        end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

def clean_encoding(text):
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã': 'í', 'Â': '', 'â': '"'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

# --- FUNCIONES DE VISUALIZACIÓN DE BÚSQUEDA (NUEVO) ---
def highlight_text(text, query):
    if not query: return text
    # Regex para case-insensitive replace manteniendo el caso original
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f'<span style="background-color: #FFD700; color: #000; padding: 2px 4px; border-radius: 4px; font-weight: bold;">{m.group(0)}</span>', text)

# --- NÚCLEO DE TRANSCRIPCIÓN ROBUSTA ---
def transcribe_audio_robust(client, file_path, model, language):
    full_segments = []
    full_text = ""
    
    try:
        if MOVIEPY_AVAILABLE:
            audio_clip = AudioFileClip(file_path)
            duration = audio_clip.duration
            chunk_size = 600  # 10 minutos
            
            if duration < chunk_size:
                with open(file_path, "rb") as f:
                    transcription = client.audio.transcriptions.create(
                        file=(os.path.basename(file_path), f.read()),
                        model=model, language=language, response_format="verbose_json",
                        temperature=0.0, prompt="Transcribir en español correctamente. Usar puntuación."
                    )
                return clean_encoding(transcription.text), transcription.segments
            
            num_chunks = math.ceil(duration / chunk_size)
            progress_bar = st.progress(0)
            
            for i in range(num_chunks):
                start_time = i * chunk_size
                end_time = min((i + 1) * chunk_size, duration)
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_chunk:
                    chunk_path = tmp_chunk.name
                
                subclip = audio_clip.subclip(start_time, end_time)
                subclip.write_audiofile(chunk_path, codec='libmp3lame', bitrate='64k', verbose=False, logger=None)
                
                with open(chunk_path, "rb") as f:
                    resp = client.audio.transcriptions.create(
                        file=("chunk.mp3", f.read()),
                        model=model, language=language, response_format="verbose_json",
                        temperature=0.0, prompt="Continuación de transcripción en español."
                    )
                
                chunk_text_part = ""
                for seg in resp.segments:
                    seg['start'] += start_time
                    seg['end'] += start_time
                    seg['text'] = clean_encoding(seg['text'])
                    full_segments.append(seg)
                    chunk_text_part += seg['text']
                
                full_text += chunk_text_part
                os.unlink(chunk_path)
                progress_bar.progress((i + 1) / num_chunks)
            
            audio_clip.close()
            progress_bar.empty()
            return full_text, full_segments
        else:
            st.warning("⚠️ MoviePy no detectado. Procesando archivo completo.")
            with open(file_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), f.read()),
                    model=model, language=language, response_format="verbose_json",
                    prompt="Transcribir audio en español."
                )
            return clean_encoding(transcription.text), transcription.segments

    except Exception as e:
        st.error(f"Error en transcripción: {str(e)}")
        return "", []

# --- CORRECCIÓN DE TEXTO ---
def safe_text_correction(text, client):
    if not text: return ""
    chunk_size = 3500
    text_chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    corrected_full_text = ""
    
    system_prompt = "Eres un corrector experto en español. Corrige ortografía y puntuación sin resumir."
    progress_text = st.empty()
    
    try:
        for idx, chunk in enumerate(text_chunks):
            progress_text.text(f"🤖 Corrigiendo parte {idx+1} de {len(text_chunks)}...")
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant", temperature=0.1, max_tokens=4000
            )
            corrected_full_text += response.choices[0].message.content.strip() + " "
        progress_text.empty()
        return corrected_full_text.strip()
    except Exception as e:
        st.warning(f"⚠️ Error parcial en corrección IA. Usando original.")
        return text

# --- ANÁLISIS (RESUMEN, ENTIDADES) ---
def generate_summary(text, client):
    if not text: return ""
    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Resume el texto en español en un párrafo ejecutivo."},
                {"role": "user", "content": f"{text[:5000]}"}
            ], model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat.choices[0].message.content
    except: return "Error al generar resumen."

def extract_json_data(text, client, prompt_type):
    if not text: return []
    prompts = {
        "people": '''Extrae personas y cargos. JSON: {"items": [{"name": "Nombre", "role": "Cargo", "context": "Frase"}]}''',
        "brands": '''Extrae marcas u organizaciones. JSON: {"items": [{"name": "Nombre", "type": "Tipo", "context": "Frase"}]}'''
    }
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": prompts[prompt_type]}, {"role": "user", "content": f"{text[:6000]}"}],
            model="llama-3.1-8b-instant", response_format={"type": "json_object"}, temperature=0.0
        )
        data = json.loads(chat.choices[0].message.content)
        return data.get("items", [])
    except: return []

def answer_question(question, context, client, history):
    messages = [{"role": "system", "content": "Responde basándote en el texto. Sé preciso."}]
    for qa in history:
        messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
    messages.append({"role": "user", "content": f"Texto: {context[:15000]}\n\nPregunta: {question}"})
    try:
        resp = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant")
        return resp.choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- UI PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    st.divider()
    enable_llama = st.checkbox("🤖 Corrección IA", value=True)
    enable_summary = st.checkbox("📝 Generar Resumen", value=True)
    enable_entities = st.checkbox("🔍 Extraer Datos", value=True)
    st.divider()
    if MOVIEPY_AVAILABLE:
        st.success("✅ Motor de Audio: Activo")
    else:
        st.error("⚠️ Instalar 'moviepy'")

# --- CARGA ---
st.subheader("1. Cargar Archivo")
uploaded_file = st.file_uploader("Sube tu archivo", type=None)

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    with st.spinner("🔄 Procesando..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        raw_text, segments = transcribe_audio_robust(client, tmp_path, model_option, "es")
        final_text = safe_text_correction(raw_text, client) if enable_llama else raw_text
        
        st.session_state.transcription_text = final_text
        st.session_state.segments = segments
        st.session_state.uploaded_audio = uploaded_file.getvalue()
        
        if enable_summary: st.session_state.summary = generate_summary(final_text, client)
        if enable_entities:
            st.session_state.people = extract_json_data(final_text, client, "people")
            st.session_state.brands = extract_json_data(final_text, client, "brands")
        
        os.unlink(tmp_path)
        st.rerun()

# --- RESULTADOS ---
if "transcription_text" in st.session_state:
    st.divider()
    st.audio(st.session_state.uploaded_audio, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📝 Transcripción (Búsqueda)", "📊 Resumen & Chat", "🔍 Entidades"])
    
    # --- PESTAÑA 1: BÚSQUEDA MEJORADA CON CONTEXTO ---
    with tabs[0]:
        col1, col2 = st.columns([3, 1])
        # Input vinculado a session_state
        search = col1.text_input("Buscar en texto:", key="search_input")
        
        # ERROR FIXED: Usamos on_click en el botón, NO lógica dentro del if
        col2.button("Limpiar Búsqueda", on_click=clear_search_callback, use_container_width=True)
        
        if search:
            st.subheader("📍 Resultados de búsqueda")
            segments = st.session_state.segments
            found = False
            
            for i, seg in enumerate(segments):
                if search.lower() in seg['text'].lower():
                    found = True
                    # Obtener contexto (anterior - actual - siguiente)
                    prev_text = segments[i-1]['text'] if i > 0 else ""
                    curr_text = seg['text']
                    next_text = segments[i+1]['text'] if i < len(segments)-1 else ""
                    
                    # Crear caja visual
                    with st.container():
                        c_play, c_txt = st.columns([0.1, 0.9])
                        with c_play:
                            if st.button("▶", key=f"play_{i}"):
                                set_audio_time(seg['start'])
                                st.rerun()
                        
                        with c_txt:
                            # Renderizar HTML para resaltar la palabra exacta
                            highlighted_curr = highlight_text(curr_text, search)
                            html_block = f"""
                            <div style="background-color: #1E1E1E; padding: 10px; border-radius: 5px; color: #CCCCCC; font-size: 14px;">
                                <span style="opacity: 0.6;">... {prev_text}</span> 
                                <span style="color: #FFFFFF; font-weight: 500;">{highlighted_curr}</span> 
                                <span style="opacity: 0.6;">{next_text} ...</span>
                                <div style="margin-top: 5px; font-size: 11px; color: #666;">Minuto: {format_timestamp(seg['start'])}</div>
                            </div>
                            """
                            st.markdown(html_block, unsafe_allow_html=True)
                        st.markdown("---") # Separador
            
            if not found:
                st.warning("No se encontraron coincidencias exactas.")

        st.divider()
        st.markdown("### Texto Completo")
        st.text_area("Transcripción completa", value=st.session_state.transcription_text, height=400)
        
        # Descargas
        d1, d2, d3 = st.columns(3)
        d1.download_button("Descargar TXT", st.session_state.transcription_text, "transcripcion.txt")
        d2.download_button("Descargar SRT", export_to_srt(st.session_state.segments), "subs.srt")
        with d3: create_copy_button(st.session_state.transcription_text)

    # --- PESTAÑA 2 ---
    with tabs[1]:
        if "summary" in st.session_state:
            st.info(st.session_state.summary)
        st.divider()
        for chat in st.session_state.qa_history:
            st.markdown(f"**Q:** {chat['question']}\n**A:** {chat['answer']}\n---")
        
        with st.form("chat_form"):
            q = st.text_input("Pregunta:")
            if st.form_submit_button("Enviar") and q:
                ans = answer_question(q, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history)
                st.session_state.qa_history.append({"question": q, "answer": ans})
                st.rerun()

    # --- PESTAÑA 3 ---
    with tabs[2]:
        c_p, c_b = st.columns(2)
        with c_p:
            if "people" in st.session_state:
                for p in st.session_state.people:
                    st.success(f"{p.get('name')} ({p.get('role')})")
                    st.caption(p.get('context'))
        with c_b:
            if "brands" in st.session_state:
                for b in st.session_state.brands:
                    st.info(f"{b.get('name')} ({b.get('type')})")
                    st.caption(b.get('context'))
