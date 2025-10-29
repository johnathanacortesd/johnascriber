import streamlit as st
from groq import Groq, RateLimitError, APIStatusError
import tempfile
import os
import json
import re
import time
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter

# MEJORADO: Importación de moviepy con manejo claro de su disponibilidad
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    st.error("Librería `moviepy` no encontrada. La conversión de audio no funcionará. Instala con: pip install moviepy")
    MOVIEPY_AVAILABLE = False

# --- LÓGICA DE AUTENTICACIÓN (Sin cambios) ---
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
        st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    st.stop()

# --- INICIO DE LA APP PRINCIPAL ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- INICIALIZACIÓN DE ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []
if 'brands_search' not in st.session_state:
    st.session_state.brands_search = ""

# --- FUNCIONES CALLBACK (Sin cambios) ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

def clear_brands_search_callback():
    st.session_state.brands_search = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES (Sin cambios) ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    r'\badministraci(?!ón\b)\b': 'administración', r'\bAdministraci(?!ón\b)\b': 'Administración',
    r'\bcomunicaci(?!ón\b)\b': 'comunicación', r'\bComunicaci(?!ón\b)\b': 'Comunicación',
    r'\bdeclaraci(?!ón\b)\b': 'declaración', r'\bDeclaraci(?!ón\b)\b': 'Declaración',
    r'\binformaci(?!ón\b)\b': 'información', r'\bInformaci(?!ón\b)\b': 'Información',
    r'\borganizaci(?!ón\b)\b': 'organización', r'\bOrganizaci(?!ón\b)\b': 'Organización',
    r'\bpolític(?!a\b)\b': 'política', r'\bPolític(?!a\b)\b': 'Política',
    r'\bRepúblic(?!a\b)\b': 'República', r'\brepúblic(?!a\b)\b': 'república',
    r'\btecnolog(?!ía\b)\b': 'tecnología', r'\bTecnolog(?!ía\b)\b': 'Tecnología',
    r'\bBogot(?!á\b)\b': 'Bogotá', r'\bMéxic(?!o\b)\b': 'México', r'\bPer\b': 'Perú',
    r'\btambi(?!én\b)\b': 'también', r'\bTambi(?!én\b)\b': 'También',
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué',
    r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde',
    r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES (Sin cambios) ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};
</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â\u00bf': '\u00bf', 'Â\u00a1': '\u00a1'
    }
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', lambda m: m.group(1) + m.group(2).upper(), result)
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result.strip()

# --- MEJORADO: FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---
def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

def convert_to_optimized_mp3(file_bytes, filename, target_bitrate='96k'):
    if not MOVIEPY_AVAILABLE:
        return file_bytes, False, "MoviePy no disponible."

    original_size = get_file_size_mb(file_bytes)
    file_ext = os.path.splitext(filename)[1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path.rsplit('.', 1)[0] + '_converted.mp3'
    
    try:
        if file_ext in ['.mp4', '.mpeg', '.webm', '.avi', '.mov', '.mkv']:
            with VideoFileClip(input_path) as video:
                video.audio.write_audiofile(output_path, codec='libmp3lame', bitrate=target_bitrate, fps=16000, nbytes=2, verbose=False, logger=None)
        else:
            with AudioFileClip(input_path) as audio:
                audio.write_audiofile(output_path, codec='libmp3lame', bitrate=target_bitrate, fps=16000, nbytes=2, verbose=False, logger=None)
        
        with open(output_path, 'rb') as f:
            mp3_bytes = f.read()
            
        final_size = get_file_size_mb(mp3_bytes)
        reduction = ((original_size - final_size) / original_size * 100) if original_size > 0 else 0
        
        if final_size < original_size:
            msg = f"✅ Archivo optimizado para transcripción: {original_size:.2f} MB → {final_size:.2f} MB (reducción del {reduction:.1f}%)"
        else:
            msg = f"✅ Archivo convertido a MP3 optimizado: {final_size:.2f} MB"
            
        return mp3_bytes, True, msg
        
    except Exception as e:
        msg = f"⚠️ Falló la optimización de audio: {str(e)}. Se usará el archivo original."
        return file_bytes, False, msg
        
    finally:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)

# --- NUEVO: FUNCIÓN ROBUSTA PARA LLAMADAS A LA IA ---
def robust_llama_completion(client, messages, model, fallback_model=None, max_retries=3, **kwargs):
    """
    Realiza una llamada a la API de Groq con reintentos y fallback opcional.
    """
    current_model = model
    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=messages,
                model=current_model,
                **kwargs
            )
            return chat_completion.choices[0].message.content
        except (RateLimitError, APIStatusError) as e:
            if e.status_code in [429, 503] and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                st.warning(f"🤖 Modelo '{current_model}' sobrecargado. Reintentando en {wait_time}s... (Intento {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                # Opcional: Cambiar a modelo de fallback
                if fallback_model:
                    current_model = fallback_model
            else:
                st.error(f"❌ Error de API persistente con '{current_model}': {str(e)}")
                return None
        except Exception as e:
            st.error(f"❌ Error inesperado al llamar a la IA: {str(e)}")
            return None
    return None

# --- FUNCIONES DE ANÁLISIS (ADAPTADAS PARA USAR robust_llama_completion) ---
def post_process_with_llama(transcription_text, client):
    messages = [
        {"role": "system", "content": """Eres un micro-servicio de corrección de texto, no un editor. Tu comportamiento es estrictamente reglado.

**REGLAS INVIOLABLES:**
1.  **ACENTUACIÓN PRECISA:** Tu tarea principal es añadir tildes faltantes a palabras que inequívocamente las requieren (ej: `como` -> `cómo`, `esta` -> `está`, `mas` -> `más`).
2.  **COMPLETAR PALABRAS:** Únicamente completarás palabras con terminaciones obvias y comunes en transcripciones (ej: `informaci` -> `información`, `tecnolog` -> `tecnología`).
3.  **NO CAMBIAR PALABRAS VÁLIDAS:** Si una palabra ya es correcta y existe en el diccionario español, NO la modificarás bajo ninguna circunstancia.
4.  **PROHIBIDO INVENTAR, OMITIR O REESCRIBIR:** No puedes añadir, eliminar ni cambiar el orden de las palabras. No puedes reescribir frases.
5.  **DEVOLVER TEXTO ÍNTEGRO:** Siempre devolverás el texto completo, aplicando únicamente las correcciones permitidas.

Tu salida debe ser únicamente el texto corregido."""},
        {"role": "user", "content": f"Aplica tus reglas de corrección a la siguiente transcripción. No alteres nada más:\n\n{transcription_text}"}
    ]
    corrected_text = robust_llama_completion(client, messages, model="llama-3.1-8b-instant", temperature=0.0, max_tokens=4096)
    return corrected_text if corrected_text else transcription_text

def generate_summary(transcription_text, client):
    messages = [
        {"role": "system", "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes profesionales y concisos en un solo párrafo. Mantén todas las tildes y acentos correctos en español."},
        {"role": "user", "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) del siguiente texto:\n\n{transcription_text}"}
    ]
    summary = robust_llama_completion(client, messages, model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500)
    return summary if summary else "No se pudo generar el resumen debido a un error."

def answer_question(question, transcription_text, client, conversation_history):
    messages = [{"role": "system", "content": "Eres un asistente experto en análisis de contenido. Responde preguntas sobre la transcripción de manera precisa y concisa, basándote ÚNICAMENTE en la información proporcionada. Si la información no está en la transcripción, indícalo claramente. Considera el historial de la conversación para preguntas de seguimiento."}]
    for qa in conversation_history:
        messages.append({"role": "user", "content": qa["question"]})
        messages.append({"role": "assistant", "content": qa["answer"]})
    messages.append({"role": "user", "content": f"Transcripción:\n---\n{transcription_text}\n---\nPregunta: {question}"})
    
    answer = robust_llama_completion(client, messages, model="llama-3.1-8b-instant", temperature=0.2, max_tokens=800)
    return answer if answer else "No se pudo procesar la pregunta debido a un error."

def extract_people_and_roles(transcription_text, client):
    messages=[
        {"role": "system", "content": '''Eres un analista de inteligencia. Identifica TODAS las personas mencionadas.
REGLAS:
1. Extrae nombres completos de personas (NO organizaciones)
2. Incluye el cargo/rol si se menciona, sino usa "Rol no especificado"
3. Proporciona el contexto (frase donde se menciona)
FORMATO DE SALIDA (JSON válido):
{ "personas": [ { "name": "Nombre", "role": "Cargo", "context": "Contexto" } ] }
Si no hay personas, devuelve: {"personas": []}'''},
        {"role": "user", "content": f"Analiza esta transcripción:\n\n{transcription_text[:3500]}"}
    ]
    response_json = robust_llama_completion(client, messages, model="llama-3.1-8b-instant", temperature=0.0, max_tokens=1500, response_format={"type": "json_object"})
    
    try:
        if not response_json: return []
        data = json.loads(response_json)
        people = data.get('personas', [])
        return people
    except (json.JSONDecodeError, TypeError):
        return []

def extract_brands_and_entities(transcription_text, client):
    messages=[
        {"role": "system", "content": '''Eres un analista de inteligencia. Identifica TODAS las marcas, empresas y organizaciones.
REGLAS:
1. Extrae nombres de entidades (NO personas)
2. Clasifica como: Empresa, Institución, ONG, Marca, Organización
3. Proporciona el contexto EXACTO (copia la frase completa donde se menciona)
FORMATO DE SALIDA (JSON válido):
{ "entidades": [ { "name": "Nombre", "type": "Tipo", "context": "Contexto exacto de la transcripción" } ] }
Si no hay entidades, devuelve: {"entidades": []}'''},
        {"role": "user", "content": f"Analiza esta transcripción:\n\n{transcription_text[:4000]}"}
    ]
    response_json = robust_llama_completion(client, messages, model="llama-3.1-8b-instant", temperature=0.0, max_tokens=2000, response_format={"type": "json_object"})

    try:
        if not response_json: return []
        data = json.loads(response_json)
        brands = data.get('entidades', [])
        return brands
    except (json.JSONDecodeError, TypeError):
        return []


# --- FUNCIONES DE EXPORTACIÓN Y BÚSQUEDA (Sin cambios) ---
def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    context_segments = [{'text': segments[i]['text'].strip(), 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start_idx, end_idx)]
    return context_segments

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start_time = timedelta(seconds=seg['start'])
        end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

def find_brand_in_segments(brand_name, segments):
    matches = []
    pattern = re.compile(re.escape(brand_name), re.IGNORECASE)
    for i, seg in enumerate(segments):
        if pattern.search(seg['text']):
            matches.append(i)
    return matches

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración de Transcripción")
    # MEJORADO: Clarificación del nombre del modelo
    model_option = st.selectbox(
        "Modelo de Transcripción", 
        ["whisper-large-v3"], 
        help="El modelo más preciso disponible para transcripción de audio en español."
    )
    language = st.selectbox("Idioma del Audio", ["es"], help="Seleccionar 'es' para español maximiza la precisión.")
    
    st.markdown("---")
    st.subheader("🤖 Análisis con IA")
    enable_llama_postprocess = st.checkbox("Corrección IA de la transcripción", value=True, help="Usa Llama-3.1 para corregir tildes y errores comunes.")
    enable_summary = st.checkbox("📝 Generar resumen ejecutivo", value=True)
    enable_people = st.checkbox("👥 Extraer personas y cargos", value=True)
    enable_brands = st.checkbox("🏢 Extraer marcas y organizaciones", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider("Líneas de contexto para búsqueda", 1, 5, 2, help="Número de frases a mostrar antes y después de una coincidencia.")
    
    st.markdown("---")
    if MOVIEPY_AVAILABLE:
        st.success("""
        ✅ **Optimización de Audio Activada:**
        Todos los archivos se convierten a formato MP3 (96kbps, 16kHz mono) para máxima velocidad y precisión.
        """)
    else:
        st.warning("⚠️ **Optimización Desactivada:** La librería `moviepy` no está instalada.")
    
    st.info("💡 Soportado: MP3, MP4, WAV, M4A, WEBM, AVI, MOV, etc.")
    st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga", "avi", "mov", "mkv", "flac"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        # Limpiar estado previo
        for key in list(st.session_state.keys()):
            if key not in ['password_correct', 'password_attempted']:
                del st.session_state[key]
        st.session_state.qa_history = []
        
        try:
            file_bytes = uploaded_file.getvalue()
            
            with st.spinner("🔄 Optimizando archivo para máxima precisión..."):
                processed_bytes, was_converted, conv_message = convert_to_optimized_mp3(file_bytes, uploaded_file.name)
                st.info(conv_message)

            st.session_state.uploaded_audio_bytes = processed_bytes
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(processed_bytes)
                tmp_path = tmp.name
            
            with st.spinner("🔄 Transcribiendo con IA (modo de máxima precisión)..."):
                with open(tmp_path, "rb") as audio_file:
                    # NUEVO: Prompt para guiar al modelo a ser más exacto
                    transcription_prompt = "Esta es una transcripción de una noticia o entrevista. Transcribe el audio de manera literal, sin omitir palabras ni corregir errores gramaticales de los hablantes. Incluye todas las muletillas y pausas."
                    
                    transcription = client.audio.transcriptions.create(
                        file=(uploaded_file.name, audio_file.read()), 
                        model=model_option, 
                        language=language,
                        response_format="verbose_json",
                        prompt=transcription_prompt,
                        temperature=0.1 # MEJORADO: Ligera flexibilidad para mejorar la captura de palabras
                    )
            os.unlink(tmp_path)
            
            # Post-procesamiento
            transcription_text = fix_spanish_encoding(transcription.text)
            if enable_llama_postprocess:
                with st.spinner("🤖 Mejorando transcripción con IA..."):
                    transcription_text = post_process_with_llama(transcription_text, client)
            
            for seg in transcription.segments:
                seg['text'] = fix_spanish_encoding(seg['text'])
            
            st.session_state.transcription = transcription_text
            st.session_state.transcription_data = transcription
            
            # Análisis con IA
            with st.spinner("🧠 Generando análisis avanzado..."):
                if enable_summary: 
                    st.session_state.summary = generate_summary(transcription_text, client)
                if enable_people: 
                    st.session_state.people = extract_people_and_roles(transcription_text, client)
                if enable_brands: 
                    st.session_state.brands = extract_brands_and_entities(transcription_text, client)
            
            st.success("✅ ¡Transcripción y análisis completados!")
            st.balloons()
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error crítico durante la transcripción: {e}")

# --- SECCIÓN DE RESULTADOS (Sin cambios mayores, solo ajustes de robustez) ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo"]
    if 'people' in st.session_state and st.session_state.get('people'): 
        tab_titles.append("👥 Personas Clave")
    if 'brands' in st.session_state and st.session_state.get('brands'): 
        tab_titles.append("🏢 Marcas")
    tabs = st.tabs(tab_titles)
    
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        MATCH_LINE_STYLE = "background-color:#1e3a5f;padding:0.8rem;border-radius:6px;border-left:4px solid #fca311;color:#ffffff;"
        CONTEXT_LINE_STYLE = "background-color:#1a1a1a;padding:0.6rem;border-radius:4px;color:#b8b8b8;"
        TRANSCRIPTION_BOX_STYLE = "background-color:#0E1117;color:#FAFAFA;border:1px solid #333;border-radius:10px;padding:1.5rem;max-height:500px;overflow-y:auto;font-family:'Source Code Pro',monospace;line-height:1.7;white-space:pre-wrap;font-size:0.95rem;"
        
        col_search1, col_search2 = st.columns([4, 1])
        with col_search1: 
            search_query = st.text_input("🔎 Buscar en la transcripción:", key="search_input")
        with col_search2: 
            st.write("")
            st.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True, disabled=not search_query)

        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if not matches: 
                    st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matches)} coincidencia(s) encontrada(s).")
                    for i, match_idx in enumerate(matches, 1):
                        for ctx_seg in get_extended_context(segments, match_idx, context_lines):
                            col_t, col_c = st.columns([0.15, 0.85])
                            with col_t: 
                                st.button(f"▶️ {ctx_seg['time']}", key=f"play_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                            with col_c:
                                style = MATCH_LINE_STYLE if ctx_seg['is_match'] else CONTEXT_LINE_STYLE
                                text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx_seg['text']) if ctx_seg['is_match'] else ctx_seg['text']
                                st.markdown(f"<div style='{style}'>{text}</div>", unsafe_allow_html=True)
                        if i < len(matches): 
                            st.markdown("---")
        
        st.markdown("📄 Transcripción completa:")
        html = st.session_state.transcription.replace('\n', '<br>')
        if search_query: 
            html = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', html)
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{html}</div>', unsafe_allow_html=True)
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        with c1: 
            st.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        with c2: 
            st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", use_container_width=True)
        with c3: 
            st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with c4: 
            create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            st.markdown("---")
            st.markdown("### 💭 Haz preguntas sobre el contenido")
            
            if st.session_state.qa_history:
                st.markdown("#### 📚 Historial de conversación")
                for i, qa in enumerate(st.session_state.qa_history):
                    st.markdown(f"**Pregunta {i+1}:** {qa['question']}")
                    st.markdown(f"**Respuesta:** {qa['answer']}")
                    st.markdown("---")

            with st.form(key="q_form", clear_on_submit=True):
                user_q = st.text_area("Escribe tu pregunta aquí:", height=100)
                s_q, c_h = st.columns(2)
                with s_q:
                    submit_question = st.form_submit_button("🚀 Enviar Pregunta", use_container_width=True)
                with c_h:
                    clear_history = st.form_submit_button("🗑️ Borrar Historial", use_container_width=True)

                if submit_question and user_q.strip():
                    with st.spinner("🤔 Analizando..."):
                        ans = answer_question(user_q, st.session_state.transcription, client, st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': user_q, 'answer': ans})
                        st.rerun()
                
                if clear_history:
                    st.session_state.qa_history = []
                    st.rerun()
        else: 
            st.info("📝 El resumen no fue generado. Activa la opción en el sidebar y vuelve a transcribir.")
    
    tab_idx = 2
    if 'people' in st.session_state and st.session_state.get('people'):
        with tabs[tab_idx]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            for person in st.session_state.people:
                st.markdown(f"**👤 {person.get('name', 'N/A')}** | **Rol:** *{person.get('role', 'N/A')}*")
                with st.expander("Ver contexto"): 
                    st.markdown(f"> {person.get('context', 'N/A')}")
        tab_idx += 1

    if 'brands' in st.session_state and st.session_state.get('brands'):
        with tabs[tab_idx]:
            st.markdown("### 🏢 Marcas y Organizaciones Mencionadas")
            
            col_brand_search1, col_brand_search2 = st.columns([4, 1])
            with col_brand_search1: 
                brand_search_query = st.text_input("🔎 Buscar marca específica:", key="brands_search")
            with col_brand_search2: 
                st.write("")
                st.button("🗑️ Limpiar", on_click=clear_brands_search_callback, use_container_width=True, disabled=not brand_search_query, key="clear_brands_btn")
            
            brands_to_show = st.session_state.brands
            if brand_search_query:
                pattern = re.compile(re.escape(brand_search_query), re.IGNORECASE)
                brands_to_show = [b for b in st.session_state.brands if pattern.search(b.get('name', ''))]
                if brands_to_show:
                    st.success(f"✅ {len(brands_to_show)} marca(s) encontrada(s).")
                else:
                    st.info("❌ No se encontraron marcas con ese nombre.")
            
            for brand in brands_to_show:
                brand_name = brand.get('name', 'N/A')
                brand_type = brand.get('type', 'N/A')
                
                st.markdown(f"**🏢 {brand_name}** | **Tipo:** *{brand_type}*")
                
                with st.expander("Ver contexto y menciones en audio"):
                    st.markdown(f"**Contexto identificado por IA:**")
                    st.markdown(f"> {brand.get('context', 'Sin contexto')}")
                    
                    segments = st.session_state.transcription_data.segments
                    matches = find_brand_in_segments(brand_name, segments)
                    
                    if matches:
                        st.markdown(f"**📍 {len(matches)} mención(es) encontrada(s) en la transcripción:**")
                        st.markdown("---")
                        
                        for match_idx in matches:
                            context_segments = get_extended_context(segments, match_idx, context_lines)
                            
                            for ctx_seg in context_segments:
                                col_time, col_text = st.columns([0.15, 0.85])
                                
                                with col_time:
                                    st.button(f"▶️ {ctx_seg['time']}", key=f"brand_play_{brand_name}_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                                
                                with col_text:
                                    if ctx_seg['is_match']:
                                        pattern = re.compile(re.escape(brand_name), re.IGNORECASE)
                                        highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx_seg['text'])
                                        st.markdown(f"<div style='{MATCH_LINE_STYLE}'>{highlighted_text}</div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown(f"<div style='{CONTEXT_LINE_STYLE}'>{ctx_seg['text']}</div>", unsafe_allow_html=True)
                            st.markdown("---")
                    else:
                        st.info("ℹ️ No se encontraron menciones exactas en los segmentos de la transcripción.")

# --- Pie de página y Limpieza ---
st.markdown("---")
if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
    pwd_ok = st.session_state.get('password_correct', False)
    st.session_state.clear()
    st.session_state.password_correct = pwd_ok
    st.rerun()

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p><strong>Transcriptor Pro - Johnascriptor - v4.0.0</strong></p>
    <p style='font-size: 0.9rem;'>🎙️ whisper-large-v3 | 🤖 llama-3.1-8b-instant (con reintentos) | 🎵 Optimización MP3 Universal</p>
    <p style='font-size: 0.8rem;'>Desarrollado por Johnathan Cortés</p>
</div>
""", unsafe_allow_html=True)
