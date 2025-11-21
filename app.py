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
        <p style='color: #666; margin-bottom: 2rem;'>Versión Mejorada - Transcripción Exacta</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro - V9", page_icon="🎙️", layout="wide")

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

def clean_whisper_artifacts(text):
    """
    Elimina artefactos repetitivos comunes de Whisper.
    Se ha simplificado para evitar cortar contenido real.
    """
    if not text:
        return text
    
    # Patrones específicos de alucinaciones de Whisper
    patterns_to_remove = [
        r'(Palabras clave[.\s]*){2,}',
        r'(Subtítulos[.\s]*){2,}',
        r'(Música[.\s]*){3,}',
        r'(\[Música\][.\s]*){2,}',
    ]
    
    result = text
    for pattern in patterns_to_remove:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    # Limpiar espacios múltiples (respetando saltos de línea)
    result = re.sub(r'[ \t]{2,}', ' ', result)
    
    # Corrección de puntos suspensivos (SOLUCIÓN ERROR SINTAXIS)
    result = re.sub(r'\.{4,}', '...', result)
    
    return result.strip()

def fix_spanish_encoding_light(text):
    """
    Solo corrige errores de codificación UTF-8 evidentes (Mojibake).
    NO toca palabras normales.
    """
    if not text: return text
    result = text
    
    # Mapa de corrección de doble codificación UTF-8 -> Latin-1 -> UTF-8
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\u00d1': 'Ñ', 'Â\u00bf': '¿', 'Â\u00a1': '¡',
        'Ã\u00c1': 'Á', 'Ã\u0089': 'É', 'Ã\u00cd': 'Í', 'Ã\u0093': 'Ó', 'Ã\u009a': 'Ú'
    }
    
    # Solo aplicamos si detectamos caracteres sospechosos para evitar falsos positivos
    if any(x in result for x in ['Ã', 'Â']):
        for wrong, correct in replacements.items():
            result = result.replace(wrong, correct)
    
    return result.strip()

def fix_accents_deterministic(text):
    """
    Corrección básica sin IA.
    NOTA: Si Whisper funciona bien, esto no debería ser necesario.
    """
    # Palabras muy específicas que suelen fallar
    accent_corrections = {
        r'\btelefonia\b': 'telefonía', r'\btecnologia\b': 'tecnología',
        r'\badministracion\b': 'administración', r'\bcomunicacion\b': 'comunicación',
        r'\binformacion\b': 'información', r'\bsolucion\b': 'solución'
    }
    
    result = text
    # Flags=re.IGNORECASE para que coincida mayúsculas/minúsculas
    for pattern, replacement in accent_corrections.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result

def text_chunker_smart(text, chunk_size=3000):
    chunks = []
    current_chunk = ""
    # Regex mejorado para no romper en abreviaturas comunes
    sentences = re.split(r'(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚÑ¡¿])', text)
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 < chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def post_process_conservative(transcription_text, client):
    """Post-procesamiento con Llama 3 para tildes."""
    chunks = text_chunker_smart(transcription_text)
    cleaned_chunks = []
    
    progress_text = "🧠 Revisando ortografía con IA..."
    my_bar = st.progress(0, text=progress_text)
    total_chunks = len(chunks)

    system_prompt = """Eres un editor de texto experto en español.
TU ÚNICA TAREA: Corregir ortografía y tildes (acentos) faltantes.
IMPORTANTE: 
- NO cambies palabras.
- NO resumas.
- NO elimines nada.
- Mantén el texto EXACTAMENTE igual, solo añade las tildes que faltan (ej: comunicacion -> comunicación).
Responde solo con el texto corregido."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk}
                ],
                model="llama-3.1-8b-instant", 
                temperature=0.1,
                max_tokens=len(chunk) + 500
            )
            corrected = response.choices[0].message.content.strip()
            
            # Control de seguridad: si el tamaño cambia drásticamente, descartar cambios
            if abs(len(corrected) - len(chunk)) > len(chunk) * 0.2:
                cleaned_chunks.append(chunk) # Usar original por seguridad
            else:
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
                {"role": "system", "content": "Genera un resumen ejecutivo en español (bullet points) del siguiente texto."},
                {"role": "user", "content": f"{transcription_text[:15000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción. Sé preciso."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Contexto:\n{transcription_text[:25000]}\n\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

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
    
    # CAMBIO IMPORTANTE: Por defecto 'Ninguna' para evitar romper palabras
    correction_mode = st.radio(
        "🤖 Modo de corrección:",
        ["Ninguna (Recomendado)", "Diccionario Básico", "IA Completa"],
        index=0,
        help="Selecciona 'Ninguna' para obtener la transcripción exacta de Whisper sin modificaciones."
    )
    
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    
    st.markdown("---")
    
    with st.expander("⚙️ Configuración Whisper"):
        temperature_whisper = st.slider("Creatividad (Temperatura)", 0.0, 1.0, 0.0, 0.1)
        use_custom_prompt = st.checkbox("Usar prompt experto", value=True)
        
        if use_custom_prompt:
            custom_prompt = st.text_area(
                "Prompt del Sistema:",
                value="Transcripción en español latino. Usa tildes, puntuación correcta y signos de interrogación. Escribe palabras completas: 'comunicación', 'canción', 'estás'.",
                height=100
            )

st.subheader("📤 Sube tu archivo")
uploaded_file = st.file_uploader("Arrastra tu audio aquí", type=["mp3", "mp4", "wav", "m4a", "mpeg"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    try:
        # 1. OPTIMIZACIÓN
        with st.spinner("🔄 Preparando audio..."):
            file_bytes, conversion_info = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = file_bytes

        client = Groq(api_key=api_key)
        
        # 2. TRANSCRIPCIÓN
        with st.spinner("🔄 Transcribiendo (Whisper Large V3)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # Prompt optimizado para evitar el error "columnicación"
            prompt_text = custom_prompt if use_custom_prompt else "Español correcto."
            
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_file.read()), 
                    model="whisper-large-v3", 
                    language="es",
                    response_format="verbose_json",
                    temperature=temperature_whisper,
                    prompt=prompt_text
                )
            os.unlink(tmp_path)
        
        # 3. LIMPIEZA BÁSICA (Sin romper palabras)
        transcription_text = fix_spanish_encoding_light(transcription.text)
        transcription_text = clean_whisper_artifacts(transcription_text)
        
        # 4. POST-PROCESAMIENTO OPCIONAL
        if correction_mode == "Diccionario Básico":
            transcription_text = fix_accents_deterministic(transcription_text)
            st.info("ℹ️ Corrección por diccionario aplicada.")
        elif correction_mode == "IA Completa":
            transcription_text = post_process_conservative(transcription_text, client)
            st.info("ℹ️ Corrección por IA aplicada.")
        
        st.session_state.transcription = transcription_text
        st.session_state.transcription_data = transcription
        
        if enable_summary:
            with st.spinner("📝 Resumiendo..."):
                st.session_state.summary = generate_summary(transcription_text, client)
        
        st.success("✅ ¡Transcripción finalizada!")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# --- VISUALIZACIÓN ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📝 Texto", "📊 Resumen / Chat"])
    
    with tab1:
        col1, col2 = st.columns([4, 1])
        search_query = col1.text_input("🔎 Buscar:", key="search_input")
        col2.write(""); col2.button("Limpiar", on_click=clear_search_callback)

        # BÚSQUEDA
        if search_query:
            matches = [m for m in re.finditer(re.escape(search_query), st.session_state.transcription, re.IGNORECASE)]
            if matches:
                st.write(f"Encontradas {len(matches)} coincidencias.")
                for match in matches[:5]: # Mostrar primeras 5
                    start = max(0, match.start() - 50)
                    end = min(len(st.session_state.transcription), match.end() + 50)
                    st.markdown(f"...{st.session_state.transcription[start:end]}...")
            else:
                st.warning("No se encontraron coincidencias.")

        st.text_area("Transcripción:", st.session_state.transcription, height=400)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.download_button("Descargar TXT", st.session_state.transcription, "transcripcion.txt")
        c2.download_button("Descargar SRT", export_to_srt(st.session_state.transcription_data), "subs.srt")
        with c4: create_copy_button(st.session_state.transcription)

    with tab2:
        if 'summary' in st.session_state:
            st.markdown(st.session_state.summary)
            st.divider()
            
            for qa in st.session_state.qa_history:
                st.markdown(f"**P:** {qa['question']}")
                st.markdown(f"**R:** {qa['answer']}")
            
            q = st.text_input("Pregunta al audio:")
            if st.button("Preguntar") and q:
                ans = answer_question(q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                st.session_state.qa_history.append({'question': q, 'answer': ans})
                st.rerun()
