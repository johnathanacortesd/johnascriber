import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta

# --- DEPENDENCIAS DE AUDIO ---
# Asegúrate de tener ffmpeg instalado en el sistema.
# En Streamlit Cloud, crea un archivo packages.txt y añade: ffmpeg
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Transcriptor Pro V4", page_icon="🎙️", layout="wide")

if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

# --- AUTENTICACIÓN ---
def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        del st.session_state["password"]
    else:
        st.session_state.password_correct = False

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align: center;'>🎙️ Transcriptor Pro</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- UTILS Y ESTADO ---
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- 1. MOTOR DE AUDIO OPTIMIZADO (LA CLAVE DEL TAMAÑO) ---
def optimize_audio(file_bytes, file_name):
    """
    Convierte CUALQUIER audio a MP3, Mono, 16kHz, 32kbps.
    Esto reduce el tamaño drásticamente sin perder calidad para Whisper.
    """
    if not MOVIEPY_AVAILABLE:
        return file_bytes, "⚠️ MoviePy no instalado. Usando original."

    try:
        # Guardar archivo original temporalmente
        ext = os.path.splitext(file_name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name

        output_path = input_path + "_opt.mp3"

        # Conversión con MoviePy
        # codec='libmp3lame' es estándar. bitrate='32k' es suficiente para voz.
        # fps=16000 es la frecuencia nativa de Whisper (evita resampleo en el servidor).
        audio_clip = AudioFileClip(input_path)
        audio_clip.write_audiofile(
            output_path,
            codec='libmp3lame',
            bitrate='32k', 
            fps=16000,
            nbytes=2,
            ffmpeg_params=["-ac", "1"], # Forzar MONO (1 canal) reduce el tamaño al 50%
            verbose=False,
            logger=None
        )
        audio_clip.close()

        # Leer resultado
        with open(output_path, 'rb') as f:
            optimized_bytes = f.read()

        # Calcular ahorro
        orig_size = len(file_bytes) / (1024*1024)
        new_size = len(optimized_bytes) / (1024*1024)
        reduction = (1 - (new_size / orig_size)) * 100

        # Limpieza
        os.unlink(input_path)
        os.unlink(output_path)

        return optimized_bytes, f"✅ Audio comprimido: {orig_size:.2f}MB ➝ {new_size:.2f}MB (Reducción: {reduction:.0f}%)"

    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        return file_bytes, f"⚠️ Error optimizando audio: {str(e)}. Usando original."

# --- 2. LIMPIEZA DE CODIFICACIÓN (MOJIBAKE) ---
def fix_encoding(text):
    """Arregla caracteres rotos comunes en conversiones UTF-8/Latin-1"""
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
        'Ã\x81': 'Á', 'Ã\x89': 'É', 'Ã\x8d': 'Í', 'Ã\x93': 'Ó', 'Ã\x9a': 'Ú', 'Ã\x91': 'Ñ',
        'Â¿': '¿', 'Â¡': '¡'
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text

# --- 3. PROCESAMIENTO INTELIGENTE POR TROZOS (LA CLAVE DE LA CALIDAD) ---
def text_chunker(text, chunk_size=3000):
    """Divide el texto en trozos respetando los puntos para no cortar frases."""
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

def clean_transcription_with_ai(full_text, client):
    """
    Limpia la transcripción por partes para evitar que la IA resuma o alucine.
    """
    chunks = text_chunker(full_text)
    cleaned_chunks = []
    
    progress_bar = st.progress(0)
    total_chunks = len(chunks)

    system_prompt = """Eres un editor de texto experto en español. 
TU TAREA: Corregir ortografía, acentuación (tildes) y puntuación del siguiente texto transcrito.
REGLAS CRÍTICAS:
1. NO resumas. El texto de salida debe tener aproximadamente la misma longitud que la entrada.
2. NO elimines palabras repetidas si dan contexto (titubeos leves se pueden quitar, pero no frases enteras).
3. Asegura el uso correcto de tildes en: pretéritos (llegó vs llego), interrogativos (qué, cómo), y palabras comunes (administración, público).
4. Devuelve SOLO el texto corregido, sin introducciones."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Texto a corregir:\n\n{chunk}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.1, # Bajo para ser fiel al texto
                max_tokens=len(chunk) + 500 # Espacio suficiente
            )
            corrected = response.choices[0].message.content.strip()
            cleaned_chunks.append(corrected)
        except Exception as e:
            cleaned_chunks.append(chunk) # Si falla, usa el original
        
        progress_bar.progress((i + 1) / total_chunks)
    
    progress_bar.empty()
    return " ".join(cleaned_chunks)

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro V4 - Optimizado")

with st.sidebar:
    st.header("Configuración")
    model = st.selectbox("Modelo", ["whisper-large-v3"], disabled=True)
    enable_ai_clean = st.checkbox("✨ Limpieza IA (Tildes/Puntuación)", value=True, help="Usa Llama para corregir ortografía sin cortar el texto.")
    st.info("💡 Ahora el sistema convierte todo a MP3 32kbps antes de enviar. Transcripciones más rápidas y sin errores de tamaño.")

uploaded_file = st.file_uploader("Arrastra tu audio/video aquí", type=["mp3", "mp4", "m4a", "wav", "mpeg", "ogg"])

if uploaded_file and st.button("🚀 Transcribir", type="primary", use_container_width=True):
    client = Groq(api_key=api_key)
    st.session_state.qa_history = []
    
    # 1. Optimización
    with st.spinner("🛠️ Comprimiendo y convirtiendo a MP3 Mono..."):
        file_bytes = uploaded_file.getvalue()
        optimized_bytes, msg = optimize_audio(file_bytes, uploaded_file.name)
        st.success(msg)
    
    # 2. Transcripción
    with st.spinner("📝 Transcribiendo con Whisper V3..."):
        # Guardar bytes optimizados a temp
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_audio:
            tmp_audio.write(optimized_bytes)
            tmp_audio_path = tmp_audio.name
        
        with open(tmp_audio_path, "rb") as f:
            # PROMPT DE CONTEXTO: Esto mejora drásticamente las tildes iniciales
            prompt_context = "Transcripción en español latinoamericano. Uso correcto de tildes, signos de puntuación y gramática. Palabras clave: administración, qué, cómo, cuándo, público, político, comunicación."
            
            transcription = client.audio.transcriptions.create(
                file=("audio.mp3", f.read()),
                model="whisper-large-v3",
                language="es",
                response_format="verbose_json",
                temperature=0.0,
                prompt=prompt_context # <--- CLAVE PARA LA CALIDAD
            )
        os.unlink(tmp_audio_path)
        
        raw_text = fix_encoding(transcription.text)
        
    # 3. Post-procesamiento
    final_text = raw_text
    if enable_ai_clean:
        with st.spinner("🧠 IA Revisando ortografía bloque a bloque..."):
            final_text = clean_transcription_with_ai(raw_text, client)
            
    st.session_state.transcription = final_text
    st.session_state.segments = transcription.segments # Guardamos segmentos originales para tiempos
    st.rerun()

# --- RESULTADOS ---
if 'transcription' in st.session_state:
    st.markdown("---")
    
    # Tabs para organizar
    tab1, tab2 = st.tabs(["📄 Texto Completo", "⏱️ Por Segmentos"])
    
    with tab1:
        st.subheader("Transcripción Final")
        st.text_area("Resultado:", value=st.session_state.transcription, height=400)
        
        st.download_button(
            "💾 Descargar TXT", 
            st.session_state.transcription, 
            file_name="transcripcion.txt",
            mime="text/plain"
        )
        
    with tab2:
        st.subheader("Segmentos con Tiempo")
        # Mostrar segmentos originales (útil para buscar)
        # Nota: La limpieza IA se hace al texto completo, los segmentos mantienen el texto original de Whisper
        # pero les aplicamos el fix_encoding básico.
        srt_text = ""
        for seg in st.session_state.segments:
            start = str(timedelta(seconds=int(seg['start'])))
            text = fix_encoding(seg['text'])
            st.markdown(f"**[{start}]** {text}")
            srt_text += f"[{start}] {text}\n"
            
        st.download_button("💾 Descargar con Tiempos", srt_text, "tiempos.txt")

    st.markdown("---")
    st.header("🤖 Chat con la Transcripción")
    
    # Chat simple
    user_q = st.text_input("Pregunta algo sobre el audio:")
    if user_q:
        with st.spinner("Analizando..."):
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Responde basándote solo en el texto proporcionado."},
                    {"role": "user", "content": f"Texto: {st.session_state.transcription[:15000]}\n\nPregunta: {user_q}"}
                ],
                model="llama-3.1-8b-instant"
            )
            st.write(completion.choices[0].message.content)
