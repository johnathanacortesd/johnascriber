import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
import difflib

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
        <h2>Transcriptor Pro - Exact Edition</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Transcripción literal y corrección ortográfica quirúrgica</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Exacto V9", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# --- FUNCIONES DE LIMPIEZA DE ALUCINACIONES (ANTI-INVENTOS) ---
def remove_whisper_hallucinations(text):
    """
    Elimina frases comunes que Whisper V3 inventa durante silencios
    y repeticiones bucleadas.
    """
    # 1. Frases de copyright/subtítulos que Whisper alucina
    hallucinations = [
        r"Subtítulos realizados por.*",
        r"Comunidad de editores.*",
        r"Amara\.org.*",
        r"Transcribed by.*",
        r"Sujeto a.*licencia.*",
        r"Copyright.*",
        r"Gracias por ver.*",
        r"Suscríbete.*"
    ]
    
    cleaned_text = text
    for pattern in hallucinations:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)
    
    # 2. Eliminar repeticiones consecutivas (ej: "hola hola hola")
    # Busca palabras repetidas 3 o más veces
    cleaned_text = re.sub(r'\b(\w+)( \1\b)+', r'\1', cleaned_text, flags=re.IGNORECASE)
    
    return cleaned_text.strip()

def filter_segments(segments):
    """Filtra segmentos completos que son probables alucinaciones"""
    clean_segments = []
    last_text = ""
    
    for seg in segments:
        text = seg['text'].strip()
        
        # Ignorar segmentos vacíos o muy cortos que suelen ser ruido
        if len(text) < 2:
            continue
            
        # Ignorar repeticiones exactas del segmento anterior (bucle de Whisper)
        if text.lower() == last_text.lower():
            continue
            
        # Ignorar frases de alucinación común
        if any(re.search(h, text, re.IGNORECASE) for h in [r"Subtítulos", r"Amara\.org", r"Editores"]):
            continue
            
        clean_segments.append(seg)
        last_text = text
        
    return clean_segments

# --- CHUNKING INTELIGENTE ---
def smart_chunker(text, chunk_size=2000):
    """Divide el texto respetando los puntos finales para no cortar oraciones."""
    sentences = re.split(r'(?<=[.?!])\s+', text)
    chunks = []
    current_chunk = []
    current_len = 0
    
    for sentence in sentences:
        if current_len + len(sentence) > chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_len = len(sentence)
        else:
            current_chunk.append(sentence)
            current_len += len(sentence)
            
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

# --- CORRECCIÓN QUIRÚRGICA CON LLM ---
def surgical_correction(text, client):
    """
    Usa LLM SOLO para tildes y puntuación básica. 
    Verifica que no haya reescritura creativa.
    """
    chunks = smart_chunker(text)
    corrected_text_parts = []
    
    progress_bar = st.progress(0, text="🧠 Aplicando corrección ortográfica estricta...")
    
    system_prompt = """
    Eres un corrector ortográfico estricto para transcripciones de audio.
    TU ÚNICA TAREA: Corregir tildes (acentos) y errores tipográficos obvios en español.
    
    REGLAS ABSOLUTAS (SI LAS ROMPES, FALLAS):
    1. NO cambies, añadas ni elimines palabras. El contenido debe ser LITERAL.
    2. NO resumas.
    3. NO cambies el estilo (si es informal, déjalo informal).
    4. SOLO arregla: 'teléfono' en lugar de 'telefono', 'público' en lugar de 'publico'.
    5. Mantén nombres propios y términos técnicos exactamente como están.
    
    Entrada: "la telefonia en la administracion publica"
    Salida: "la telefonía en la administración pública"
    
    Devuelve SOLAMENTE el texto corregido. Nada más.
    """

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0, # Determinístico total
                max_tokens=len(chunk) + 500
            )
            prediction = response.choices[0].message.content.strip()
            
            # --- SAFETY CHECK ---
            # Si la longitud difiere más del 15%, el modelo probablemente alucinó o resumió.
            # En ese caso, descartamos la corrección y usamos el original.
            len_ratio = len(prediction) / len(chunk) if len(chunk) > 0 else 0
            if len_ratio < 0.85 or len_ratio > 1.15:
                corrected_text_parts.append(chunk) # Usar original por seguridad
                print(f"⚠️ Chunk {i} descartado por seguridad (ratio {len_ratio:.2f})")
            else:
                corrected_text_parts.append(prediction)
                
        except Exception as e:
            corrected_text_parts.append(chunk) # Fallback al original
            
        progress_bar.progress((i + 1) / len(chunks))
        
    progress_bar.empty()
    return " ".join(corrected_text_parts)

# --- UTILIDADES UI ---
def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #ccc; background-color: #f0f2f6; cursor: pointer;">📋 Copiar al portapapeles</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar al portapapeles"}}, 2000);}};</script>"""
    components.html(button_html, height=50)

# --- OPTIMIZACIÓN AUDIO (FFMPEG) ---
def optimize_audio_standard(file_bytes, filename):
    """Convierte cualquier audio a MP3 16kHz Mono (Ideal para Whisper)"""
    file_ext = os.path.splitext(filename)[1]
    if not file_ext: file_ext = ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path + "_opt.mp3"
    
    try:
        # ffmpeg -i input -ar 16000 -ac 1 -map 0:a:0 output
        command = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", # No video
            "-ar", "16000", # Sample rate Whisper friendly
            "-ac", "1", # Mono
            "-b:a", "48k", # Bitrate suficiente para voz
            "-f", "mp3", output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(output_path, 'rb') as f:
            new_bytes = f.read()
            
        os.unlink(input_path)
        os.unlink(output_path)
        return new_bytes, True
    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, False

# --- MAIN UI ---
st.title("🎙️ Transcriptor Pro - Modo Exactitud")

with st.sidebar:
    st.header("🔧 Configuración")
    
    st.info("Este modo está diseñado para evitar 'invenciones' del modelo.")
    
    enable_cleaning = st.checkbox("🧹 Filtro Anti-Alucinaciones", value=True, help="Elimina frases repetitivas y créditos falsos (Amara, Subtítulos por...)")
    enable_correction = st.checkbox("🧠 Corrector de Tildes (LLM)", value=True, help="Usa Llama 3 para poner tildes sin cambiar palabras.")
    
    st.markdown("---")
    st.write("💡 **Tips:**")
    st.caption("- Archivos MP3/WAV funcionan mejor.")
    st.caption("- El filtro anti-alucinaciones elimina bucles de silencio.")

uploaded_file = st.file_uploader("Sube tu archivo", type=["mp3", "mp4", "wav", "m4a", "ogg"])

if st.button("🚀 Transcribir Ahora", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    try:
        # 1. PREPROCESAMIENTO
        with st.spinner("🔄 Optimizando audio (16kHz Mono)..."):
            audio_bytes, optimized = optimize_audio_standard(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.audio_bytes = audio_bytes
        
        client = Groq(api_key=api_key)
        
        # 2. TRANSCRIPCIÓN WHISPER (PARAMETROS STRICT)
        with st.spinner("📝 Transcribiendo (Whisper V3)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            with open(tmp_path, "rb") as f:
                # Temperature 0.0 es crucial para evitar invenciones
                # Prompt inicial guía el estilo
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    temperature=0.0, 
                    response_format="verbose_json",
                    prompt="Transcripción verbatim exacta. Sin parafrasear. Español."
                )
            os.unlink(tmp_path)
        
        # 3. LIMPIEZA Y FILTRADO
        if enable_cleaning:
            # Filtrar segmentos malos
            clean_segs = filter_segments(transcription.segments)
            # Reconstruir texto solo con segmentos válidos
            raw_text = " ".join([s['text'].strip() for s in clean_segs])
            # Limpieza extra regex
            raw_text = remove_whisper_hallucinations(raw_text)
            # Actualizar objeto para guardar tiempos corregidos
            transcription.segments = clean_segs 
        else:
            raw_text = transcription.text

        st.session_state.raw_text = raw_text
        st.session_state.segments = transcription.segments

        # 4. CORRECCIÓN ORTOGRÁFICA (Opcional)
        if enable_correction:
            final_text = surgical_correction(raw_text, client)
        else:
            final_text = raw_text
            
        st.session_state.final_text = final_text
        st.success("✅ ¡Proceso completado!")
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# --- VISUALIZACIÓN DE RESULTADOS ---
if 'final_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.audio_bytes)
    
    tab1, tab2, tab3 = st.tabs(["📄 Texto Final", "🔍 Comparación (Diff)", "⏱️ Tiempos"])
    
    with tab1:
        st.subheader("Transcripción Limpia")
        st.text_area("Resultado", st.session_state.final_text, height=500)
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("💾 Descargar TXT", st.session_state.final_text, "transcripcion.txt", use_container_width=True)
        with col2:
            create_copy_button(st.session_state.final_text)

    with tab2:
        st.subheader("¿Qué cambió el corrector?")
        st.info("Izquierda: Salida cruda de Whisper | Derecha: Corrección de tildes")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Whisper Original**")
            st.code(st.session_state.raw_text, language=None)
        with col_b:
            st.markdown("**Corrección LLM**")
            st.code(st.session_state.final_text, language=None)
            
        # Diff visual
        diff = difflib.ndiff(st.session_state.raw_text.splitlines(), st.session_state.final_text.splitlines())
        st.markdown("**Detalle de cambios:**")
        diff_text = '\n'.join([l for l in diff if l.startswith('+ ') or l.startswith('- ')])
        if diff_text:
            st.code(diff_text)
        else:
            st.caption("No hubo cambios significativos o el texto es idéntico.")

    with tab3:
        st.subheader("Segmentos por Tiempo")
        if 'segments' in st.session_state:
            for seg in st.session_state.segments:
                t_start = format_timestamp(seg['start'])
                t_end = format_timestamp(seg['end'])
                st.markdown(f"`[{t_start} - {t_end}]` : {seg['text']}")
