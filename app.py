import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter

# Importar para conversión de audio
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- LÓGICA DE AUTENTICACIÓN ROBUSTA ---

if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        st.session_state.password_attempted = False
        if "password" in st.session_state:
            del st.session_state.password
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    # Pantalla de login mejorada
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
            st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    
    st.stop()

# --- INICIO DE LA APP PRINCIPAL ---

st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- FUNCIONES AUXILIARES ORIGINALES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">
        📋 Copiar Todo
    </button>
    <script>
    document.getElementById("{button_id}").onclick = function() {{
        const textArea = document.createElement("textarea");
        textArea.value = {text_json};
        textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
        const button = document.getElementById("{button_id}");
        const originalText = button.innerText;
        button.innerText = "✅ ¡Copiado!";
        setTimeout(function() {{ button.innerText = originalText; }}, 2000);
    }};
    </script>
    """
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [
        f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}"
        for seg in data.segments
    ]
    return "\n".join(lines)

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---

def convert_video_to_audio(video_bytes, video_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp_video:
            tmp_video.write(video_bytes)
            video_path = tmp_video.name
        
        audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
        
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None)
        video.close()
        
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        
        os.unlink(video_path)
        os.unlink(audio_path)
        
        return audio_bytes, True
    except Exception as e:
        return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes)
            audio_path = tmp_audio.name
        
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(compressed_path, codec='mp3', bitrate='96k', verbose=False, logger=None)
        audio.close()
        
        with open(compressed_path, 'rb') as f:
            compressed_bytes = f.read()
        
        os.unlink(audio_path)
        os.unlink(compressed_path)
        
        return compressed_bytes
    except Exception as e:
        return audio_bytes

def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS ---

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes en formato de párrafo corrido, profesionales y concisos."
                },
                {
                    "role": "user",
                    "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) sobre el siguiente contenido. No uses bullet points, no uses listas numeradas, no uses introducciones como 'A continuación' o 'El resumen es'. Ve directo al contenido:\n\n{transcription_text}"
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al generar resumen: {str(e)}"

def extract_quotes(segments):
    quotes = []
    quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró', 'confirmó', 'negó', 'advirtió', 'explicó', 'destacó', 'subrayó', 'recalcó', 'sostuvo']
    
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        text_lower = text.lower()
        
        has_quotes = '"' in text or '«' in text or '»' in text
        has_declaration = any(keyword in text_lower for keyword in quote_keywords)
        
        if has_quotes or has_declaration:
            context_before = ""
            context_after = ""
            if i > 0: context_before = segments[i-1]['text'].strip()
            if i < len(segments) - 1: context_after = segments[i+1]['text'].strip()
            full_context = f"{context_before} {text} {context_after}".strip()
            
            quotes.append({
                'time': format_timestamp(seg['start']),
                'text': text,
                'full_context': full_context,
                'start': seg['start'],
                'type': 'quote' if has_quotes else 'declaration'
            })
    
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)
    return quotes[:10]

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start = format_timestamp(seg['start']).replace(':', ',')
        end = format_timestamp(seg['end']).replace(':', ',')
        text = seg['text'].strip()
        srt_content.append(f"{i}\n{start},000 --> {end},000\n{text}\n")
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    model_option = st.selectbox(
        "Modelo de Transcripción",
        options=["whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"],
        index=0,
        help="Large-v3: Máxima precisión (recomendado) | Turbo: Más rápido | Distil: Inglés optimizado"
    )
    language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0)
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0 = más preciso, 1 = más creativo")
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_summary = st.checkbox("📝 Generar resumen automático", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas y declaraciones", value=True)
    st.markdown("---")
    st.subheader("🔧 Procesamiento de Audio")
    if MOVIEPY_AVAILABLE:
        st.info("💡 Los archivos MP4 mayores a 25 MB se convertirán automáticamente a MP3")
        compress_audio_option = st.checkbox("📦 Comprimir audio adicional", value=False, help="Reduce más el tamaño (bitrate 96k). Solo para archivos muy grandes.")
    else:
        st.warning("⚠️ MoviePy no disponible. Instala para conversión de video.")
        compress_audio_option = False
    st.markdown("---")
    st.info("💡 **Formatos soportados:** MP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
    st.success("✅ API Key configurada correctamente")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.audio_start_time = 0
        st.session_state.last_search = ""
        st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
        
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                original_size = get_file_size_mb(file_bytes)
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                is_video = file_extension in ['.mp4', '.mpeg', '.mpga', '.webm']
                converted = False
                
                if is_video and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Archivo de {original_size:.2f} MB detectado. Convirtiendo a MP3..."):
                        file_bytes, converted = convert_video_to_audio(file_bytes, uploaded_file.name)
                        if converted:
                            new_size = get_file_size_mb(file_bytes)
                            reduction = ((original_size - new_size) / original_size) * 100
                            st.success(f"✅ Convertido a MP3: {original_size:.2f} MB → {new_size:.2f} MB (-{reduction:.1f}%)")
                elif is_video and original_size > 25 and not MOVIEPY_AVAILABLE:
                    st.warning(f"⚠️ Archivo de {original_size:.2f} MB. MoviePy no disponible para conversión.")
                
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo audio..."):
                        size_before = get_file_size_mb(file_bytes)
                        file_bytes = compress_audio(file_bytes, uploaded_file.name)
                        size_after = get_file_size_mb(file_bytes)
                        reduction = ((size_before - size_after) / size_before) * 100
                        st.success(f"✅ Audio comprimido: {size_before:.2f} MB → {size_after:.2f} MB (-{reduction:.1f}%)")
                
                st.session_state.uploaded_audio_bytes = file_bytes
                st.session_state.original_filename = uploaded_file.name
                
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_file_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA avanzada..."):
                    # Preparamos un "prompt" para guiar al modelo y evitar cortes con tildes.
                    # Este texto le da contexto en español y le "recuerda" el vocabulario.
                    spanish_prompt = (
                        "A continuación, se presenta la transcripción de un noticiero en español. "
                        "El análisis de la información es crucial. La situación política y económica "
                        "será discutida. Mencionaron la última sesión y la votación unánime. "
                        "También se habló de la producción y la comunicación."
                    )

                    with open(tmp_file_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model=model_option,
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json",
                            prompt=spanish_prompt,
                            word_timestamps=True
                        )
                
                os.unlink(tmp_file_path)
                st.session_state.transcription = transcription.text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary:
                        st.session_state.summary = generate_summary(transcription.text, client)
                    if enable_quotes:
                        st.session_state.quotes = extract_quotes(transcription.segments)
                
                st.success("✅ ¡Transcripción y análisis completados!")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Error durante la transcripción: {str(e)}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    st.write("")
    
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "📊 Resumen", "💬 Citas y Declaraciones"])
    
    with tab1:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        TRANSCRIPTION_BOX_STYLE = """
            background-color: #0E1117; color: #FAFAFA
