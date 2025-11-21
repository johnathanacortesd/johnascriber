import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess # <--- Importante para la corrección
from datetime import timedelta

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Transcriptor Pro V5", page_icon="🎙️", layout="wide")

# --- CSS PERSONALIZADO ---
st.markdown("""
    <style>
    .stAlert { margin-top: 1rem; }
    .success-box { padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 0.5rem; border: 1px solid #c3e6cb; }
    </style>
""", unsafe_allow_html=True)

# --- GESTIÓN DE SECRETOS ---
try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en los secrets de Streamlit.")
    st.stop()

# --- AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        del st.session_state["password"]

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align: center;'>🎙️ Transcriptor Pro</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- 1. MOTOR DE AUDIO ROBUSTO (SUBPROCESS + FFMPEG) ---
def optimize_audio_robust(file_bytes, file_ext):
    """
    Intenta comprimir usando llamada directa al sistema (FFmpeg) para evitar
    errores de decodificación de Python/MoviePy.
    Configuración: MP3 Mono 16kHz 32kbps.
    """
    # Usamos nombres genéricos para evitar errores de encoding con caracteres raros en nombres de archivo
    safe_ext = file_ext if file_ext else ".mp3"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=safe_ext) as input_tmp:
        input_path = input_tmp.name
        input_tmp.write(file_bytes)
    
    output_path = input_path + "_opt.mp3"
    
    conversion_success = False
    final_bytes = file_bytes
    log_msg = ""

    try:
        # INTENTO 1: Subprocess directo (Más estable en Linux/Cloud)
        # -y: sobrescribir | -vn: quitar video | -ar 16000: frecuencia Whisper
        # -ac 1: Mono | -b:a 32k: Bitrate bajo peso
        command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",
            "-ar", "16000",
            "-ac", "1", 
            "-b:a", "32k",
            "-f", "mp3",
            output_path
        ]
        
        # Ejecutamos silenciando la salida para evitar el error 'utf-8 codec can't decode'
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, "rb") as f:
                final_bytes = f.read()
            conversion_success = True
            log_msg = "✅ FFmpeg Nativo"
            
    except Exception as e_ffmpeg:
        # INTENTO 2: MoviePy (Solo si falla el nativo)
        try:
            from moviepy.editor import AudioFileClip
            clip = AudioFileClip(input_path)
            clip.write_audiofile(
                output_path, fps=16000, nbytes=2, codec='libmp3lame', 
                bitrate='32k', ffmpeg_params=["-ac", "1"], 
                verbose=False, logger=None 
            )
            clip.close()
            with open(output_path, "rb") as f:
                final_bytes = f.read()
            conversion_success = True
            log_msg = "✅ MoviePy (Fallback)"
        except Exception as e_moviepy:
            log_msg = f"⚠️ Falló optimización: {str(e_ffmpeg)} | {str(e_moviepy)}"
            conversion_success = False

    # Limpieza
    try:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
    except: pass

    # Cálculo de reducción
    if conversion_success:
        orig_mb = len(file_bytes) / (1024*1024)
        new_mb = len(final_bytes) / (1024*1024)
        reduction = (1 - (new_mb / orig_mb)) * 100 if orig_mb > 0 else 0
        return final_bytes, f"{log_msg}: {orig_mb:.1f}MB ➝ {new_mb:.1f}MB (-{reduction:.0f}%)"
    else:
        return file_bytes, log_msg

# --- 2. UTILIDADES DE TEXTO ---
def fix_encoding(text):
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
        'Ã\x81': 'Á', 'Ã\x89': 'É', 'Ã\x8d': 'Í', 'Ã\x93': 'Ó', 'Ã\x9a': 'Ú', 'Ã\x91': 'Ñ',
        'Â¿': '¿', 'Â¡': '¡'
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text

def text_chunker(text, chunk_size=2500):
    """Corta texto por oraciones para no romper contexto."""
    chunks = []
    current_chunk = ""
    sentences = re.split(r'(?<=[.?!])\s+', text)
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk: chunks.append(current_chunk.strip())
    return chunks

def clean_transcription_with_ai(full_text, client):
    chunks = text_chunker(full_text)
    cleaned_chunks = []
    
    progress_text = "🧠 IA corrigiendo ortografía y puntuación..."
    my_bar = st.progress(0, text=progress_text)
    
    system_prompt = """Eres un editor experto. TU TAREA: Corregir ortografía, tildes y puntuación.
    REGLAS: 1. NO resumas. 2. Mantén el texto completo. 3. Arregla tildes en: pretéritos, interrogativos y palabras clave."""
    
    for i, chunk in enumerate(chunks):
        try:
            resp = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant", temperature=0.1
            )
            cleaned_chunks.append(resp.choices[0].message.content.strip())
        except:
            cleaned_chunks.append(chunk)
        my_bar.progress((i + 1) / len(chunks), text=f"{progress_text} ({i+1}/{len(chunks)})")
    
    my_bar.empty()
    return " ".join(cleaned_chunks)

# --- INTERFAZ ---
st.title("🎙️ Transcriptor Pro V5 - Robustez Total")
st.info("✅ Versión actualizada: Manejo nativo de FFmpeg para evitar errores de codificación.")

uploaded_file = st.file_uploader("Archivo multimedia", type=["mp3", "mp4", "m4a", "wav", "mpeg", "ogg", "webm"])

if uploaded_file and st.button("🚀 Iniciar Proceso", type="primary", use_container_width=True):
    client = Groq(api_key=api_key)
    
    # 1. OPTIMIZACIÓN
    with st.spinner("🔨 Comprimiendo audio (FFmpeg)..."):
        file_ext = os.path.splitext(uploaded_file.name)[1]
        audio_bytes, msg = optimize_audio_robust(uploaded_file.getvalue(), file_ext)
        
        if "⚠️" in msg:
            st.warning(msg)
            st.error("⚠️ La optimización falló. Se intentará usar el archivo original, pero si es >25MB fallará.")
        else:
            st.success(msg)

    # 2. TRANSCRIPCIÓN
    with st.spinner("✍️ Transcribiendo..."):
        try:
            # Guardar el audio (ya sea optimizado u original)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_audio:
                tmp_audio.write(audio_bytes)
                tmp_audio_path = tmp_audio.name
            
            with open(tmp_audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()), # Nombre genérico forzado
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0,
                    prompt="Transcripción en español. Ortografía perfecta, tildes en: qué, cómo, cuándo, pasó, miró, público."
                )
            os.unlink(tmp_audio_path)
            
            raw_text = fix_encoding(transcription.text)
            st.session_state.segments = transcription.segments
            
        except Exception as e:
            st.error(f"❌ Error en API Groq: {str(e)}")
            if "413" in str(e):
                st.error("📉 El archivo es demasiado grande incluso después de intentar comprimirlo.")
            st.stop()

    # 3. LIMPIEZA IA
    final_text = raw_text
    if st.checkbox("✨ Limpieza extra con IA", value=True):
        final_text = clean_transcription_with_ai(raw_text, client)
    
    st.session_state.transcription = final_text
    st.rerun()

# --- VISUALIZACIÓN ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("📄 Resultado Final")
    st.text_area("", st.session_state.transcription, height=400)
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 Descargar Texto", st.session_state.transcription, "transcripcion.txt")
    with c2:
        if 'segments' in st.session_state:
            srt = "\n".join([f"[{timedelta(seconds=int(s['start']))}] {fix_encoding(s['text'])}" for s in st.session_state.segments])
            st.download_button("⏱️ Descargar con Tiempos", srt, "tiempos.txt")
