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

# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

# --- FUNCIÓN CALLBACK PARA LIMPIAR BÚSQUEDA ---
def clear_search_callback():
    st.session_state.search_input = ""

def clear_brands_search_callback():
    st.session_state.brands_search = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES MÍNIMAS (SOLO ORTOGRAFÍA) ---
# REDUCIDO AL MÍNIMO - Solo errores evidentes de encoding
MINIMAL_CORRECTIONS = {
    r'Ã¡': 'á', r'Ã©': 'é', r'Ã­': 'í', r'Ã³': 'ó', r'Ãº': 'ú',
    r'Ã±': 'ñ', r'Ã\'': 'Ñ',
}

# --- FUNCIONES AUXILIARES ---
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

def fix_encoding_only(text):
    """
    NUEVA FUNCIÓN: Solo arregla problemas de encoding, NO modifica contenido
    """
    if not text:
        return text
    
    result = text
    # Solo correcciones de encoding roto
    for wrong, correct in MINIMAL_CORRECTIONS.items():
        result = result.replace(wrong, correct)
    
    return result.strip()

# --- FUNCIONES DE CONVERSIÓN DE AUDIO (OPTIMIZADA) ---
def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

def universal_audio_converter(file_bytes, filename):
    """
    MEJORADO: Conversión a formato óptimo para Whisper
    - Mono (reduce tamaño 50%)
    - 16kHz (frecuencia nativa de Whisper)
    - 96kbps (mejor calidad para español)
    """
    try:
        original_size = get_file_size_mb(file_bytes)
        file_ext = os.path.splitext(filename)[1].lower()
        if not file_ext:
            file_ext = ".mp3"

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
            tmp_input.write(file_bytes)
            input_path = tmp_input.name
        
        output_path = input_path + "_opt.mp3"
        
        try:
            audio = AudioFileClip(input_path)
            
            # MEJORADO: 96kbps para mejor calidad en español
            audio.write_audiofile(
                output_path,
                codec='libmp3lame',
                bitrate='96k',      # Aumentado de 64k a 96k
                fps=16000,          # Frecuencia nativa de Whisper
                nbytes=2,
                ffmpeg_params=["-ac", "1"],  # Mono
                verbose=False,
                logger=None
            )
            
            audio.close()
            
            with open(output_path, 'rb') as f:
                mp3_bytes = f.read()
            
            final_size = get_file_size_mb(mp3_bytes)
            
            os.unlink(input_path)
            os.unlink(output_path)
            
            return mp3_bytes, True, original_size, final_size
            
        except Exception as e:
            if os.path.exists(input_path):
                os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
            return file_bytes, False, original_size, original_size
            
    except Exception:
        return file_bytes, False, 0, 0

def process_audio_for_transcription(uploaded_file):
    """
    Gestor de conversión con mejor calidad
    """
    file_bytes = uploaded_file.getvalue()
    original_size = get_file_size_mb(file_bytes)
    
    if MOVIEPY_AVAILABLE:
        processed_bytes, was_converted, orig_mb, final_mb = universal_audio_converter(file_bytes, uploaded_file.name)
        
        if was_converted:
            reduction = ((orig_mb - final_mb) / orig_mb * 100) if orig_mb > 0 else 0
            msg = f"✅ Audio optimizado: {orig_mb:.2f} MB → {final_mb:.2f} MB (Reducción {reduction:.0f}%) | MP3 Mono 16kHz 96kbps"
            return processed_bytes, {'converted': True, 'message': msg}
        else:
            return file_bytes, {'converted': False, 'message': f"⚠️ No se pudo optimizar, usando original ({original_size:.2f} MB)."}
    else:
        return file_bytes, {'converted': False, 'message': f"⚠️ MoviePy no instalado. Usando original ({original_size:.2f} MB)."}

# --- FUNCIÓN DE POST-PROCESAMIENTO CONSERVADOR ---
def conservative_postprocess(transcription_text, client):
    """
    NUEVO: Post-procesamiento ultra-conservador
    - Solo corrige tildes obvias
    - NO modifica palabras
    - NO resume ni parafrasea
    - Temperatura 0 para máxima fidelidad
    """
    try:
        system_prompt = """Eres un corrector ortográfico EXTREMADAMENTE CONSERVADOR.

REGLAS ABSOLUTAS:
1. NUNCA cambies palabras por otras (ej: "alcaldía" debe quedar exactamente así)
2. SOLO añade tildes faltantes en palabras comunes (administración, comunicación, Bogotá, público)
3. SOLO corrige puntuación básica (puntos, comas)
4. NO resumas, NO parafrasees, NO agregues introducciones
5. MANTÉN el texto EXACTAMENTE como está, solo mejora ortografía
6. Si no estás 100% seguro de un cambio, NO lo hagas
7. RESPETA nombres propios, instituciones y lugares

Devuelve SOLO el texto corregido, nada más."""

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{transcription_text}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.0,  # Máxima fidelidad
            max_tokens=8000
        )
        
        result = chat_completion.choices[0].message.content.strip()
        
        # Validación de seguridad: si el resultado es muy diferente, usar original
        original_words = len(transcription_text.split())
        result_words = len(result.split())
        
        # Si la diferencia es mayor al 5%, algo salió mal
        if abs(original_words - result_words) / original_words > 0.05:
            st.warning("⚠️ Post-procesamiento rechazado (cambios excesivos). Usando transcripción original.")
            return transcription_text
        
        return result
        
    except Exception as e:
        st.warning(f"⚠️ Post-procesamiento falló: {str(e)}. Usando transcripción original.")
        return transcription_text

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes profesionales y concisos en un solo párrafo. Mantén todas las tildes y acentos correctos en español."},
                {"role": "user", "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) del siguiente texto:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al generar resumen: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Eres un asistente experto en análisis de contenido. Responde preguntas sobre la transcripción de manera precisa y concisa, basándote ÚNICAMENTE en la información proporcionada. Si la información no está en la transcripción, indícalo claramente. Considera el historial de la conversación para preguntas de seguimiento."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Transcripción:\n---\n{transcription_text}\n---\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2, max_tokens=800
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al procesar la pregunta: {str(e)}"

def extract_people_and_roles(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": '''Eres un analista de inteligencia. Identifica TODAS las personas mencionadas.
REGLAS:
1. Extrae nombres completos de personas (NO organizaciones)
2. Incluye el cargo/rol si se menciona, sino usa "Rol no especificado"
3. Proporciona el contexto (frase donde se menciona)
FORMATO DE SALIDA (JSON válido):
{ "personas": [ { "name": "Nombre", "role": "Cargo", "context": "Contexto" } ] }
Si no hay personas, devuelve: {"personas": []}'''},
                {"role": "user", "content": f"Analiza esta transcripción:\n\n{transcription_text[:4000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.0, max_tokens=1500, response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        
        people = data.get('personas', data.get('people', [] if not isinstance(data, list) else data))
        validated = []
        for person in people:
            if isinstance(person, dict):
                validated.append({
                    "name": person.get('name', person.get('nombre', 'Desconocido')),
                    "role": person.get('role', person.get('rol', 'Rol no especificado')),
                    "context": person.get('context', person.get('contexto', 'Sin contexto'))
                })
        return validated
    except (json.JSONDecodeError, Exception):
        return []

def extract_brands_and_entities(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": '''Eres un analista de inteligencia. Identifica TODAS las marcas, empresas y organizaciones.
REGLAS:
1. Extrae nombres de entidades (NO personas)
2. Clasifica como: Empresa, Institución, ONG, Marca, Organización
3. Proporciona el contexto EXACTO (copia la frase completa donde se menciona)
FORMATO DE SALIDA (JSON válido):
{ "entidades": [ { "name": "Nombre", "type": "Tipo", "context": "Contexto exacto de la transcripción" } ] }
Si no hay entidades, devuelve: {"entidades": []}'''},
                {"role": "user", "content": f"Analiza esta transcripción:\n\n{transcription_text[:5000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.0, max_tokens=2000, response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        
        brands = data.get('entidades', data.get('entities', data.get('marcas', [] if not isinstance(data, list) else data)))
        validated = []
        for brand in brands:
            if isinstance(brand, dict):
                validated.append({
                    "name": brand.get('name', brand.get('nombre', 'Desconocido')),
                    "type": brand.get('type', brand.get('tipo', 'Tipo no especificado')),
                    "context": brand.get('context', brand.get('contexto', 'Sin contexto'))
                })
        return validated
    except (json.JSONDecodeError, Exception):
        return []

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
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3", "whisper-large-v3-turbo"], 
                                 help="Turbo: Más rápido | V3: Máxima precisión")
    language = st.selectbox("Idioma", ["es"], help="Español optimizado.")
    
    st.markdown("---")
    st.subheader("🎯 Opciones de Precisión")
    
    # NUEVO: Control de temperatura
    temperature = st.slider(
        "Temperatura Whisper", 
        0.0, 1.0, 0.0, 0.1,
        help="0.0 = Máxima fidelidad (recomendado) | Mayor = Más creativo pero menos preciso"
    )
    
    # NUEVO: Prompt personalizado
    use_custom_prompt = st.checkbox(
        "Usar prompt especializado", 
        value=True,
        help="Ayuda al modelo a reconocer palabras colombianas comunes"
    )
    
    custom_prompt = st.text_area(
        "Palabras/Entidades clave:",
        value="alcaldía, administración, comunicación, Bogotá, Cali, Colombia",
        help="Separa con comas. Ayuda al modelo a reconocer nombres propios.",
        disabled=not use_custom_prompt
    ) if use_custom_prompt else ""
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    
    # MODIFICADO: Post-procesamiento ahora es conservador
    enable_postprocess = st.checkbox(
        "🤖 Post-procesamiento conservador", 
        value=True,
        help="Solo corrige tildes obvias, NO modifica palabras"
    )
    
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_people = st.checkbox("👥 Extraer personas", value=True)
    enable_brands = st.checkbox("🏢 Extraer marcas", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2, help="Líneas antes y después.")
    
    st.markdown("---")
    if MOVIEPY_AVAILABLE:
        st.success("✅ **Motor de Audio Activo:** Conversión automática a MP3 Mono 96kbps.")
    else:
        st.warning("⚠️ MoviePy no disponible. Instala con: `pip install moviepy`")
    
    st.info("💡 Archivos grandes se optimizan automáticamente.")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga", "avi", "mov", "mkv", "flac"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        # Limpieza de estado
        for key in list(st.session_state.keys()):
            if key not in ['password_correct', 'password_attempted']:
                del st.session_state[key]
        st.session_state.audio_start_time = 0
        st.session_state.qa_history = []
        st.session_state.brands_search = ""
        
        try:
            # 1. Optimización de Audio
            with st.spinner("🔄 Optimizando archivo de audio..."):
                file_bytes, conversion_info = process_audio_for_transcription(uploaded_file)
                st.info(conversion_info['message'])

            st.session_state.uploaded_audio_bytes = file_bytes
            client = Groq(api_key=api_key)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # 2. TRANSCRIPCIÓN MEJORADA
            with st.spinner("🔄 Transcribiendo con máxima precisión..."):
                with open(tmp_path, "rb") as audio_file:
                    # PROMPT MEJORADO
                    whisper_prompt = ""
                    if use_custom_prompt and custom_prompt:
                        # Construir prompt con palabras clave
                        keywords = [w.strip() for w in custom_prompt.split(',') if w.strip()]
                        whisper_prompt = f"Transcripción en español colombiano. Palabras clave: {', '.join(keywords)}. Usar ortografía correcta con tildes."
                    
                    transcription = client.audio.transcriptions.create(
                        file=(uploaded_file.name, audio_file.read()),
                        model=model_option,
                        language=language,
                        response_format="verbose_json",
                        temperature=temperature,  # NUEVO: Temperatura configurable
                        prompt=whisper_prompt if whisper_prompt else None  # NUEVO: Prompt personalizado
                    )
            
            os.unlink(tmp_path)
            
            # 3. LIMPIEZA MÍNIMA (solo encoding)
            transcription_text = fix_encoding_only(transcription.text)
            
            # 4. POST-PROCESAMIENTO CONSERVADOR (opcional)
            if enable_postprocess:
                with st.spinner("🤖 Refinando ortografía (modo conservador)..."):
                    transcription_text = conservative_postprocess(transcription_text, client)
            
            # Limpiar segmentos también
            for seg in transcription.segments:
                seg['text'] = fix_encoding_only(seg['text'])
            
            st.session_state.transcription = transcription_text
            st.session_state.transcription_data = transcription
            
            # 5. Análisis de Entidades
            with st.spinner("🧠 Extrayendo datos clave..."):
                if enable_summary:
                    st.session_state.summary = generate_summary(transcription_text, client)
                if enable_people:
                    st.session_state.people = extract_people_and_roles(transcription_text, client)
                if enable_brands:
                    st.session_state.brands = extract_brands_and_entities(transcription_text, client)
            
            st.success("✅ ¡Transcripción Completada!")
            st.balloons()
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error crítico: {e}")
            import traceback
            st.code(traceback.format_exc())

if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo"]
    if 'people' in st.session_state and st.session_state.people:
        tab_titles.append("👥 Personas Clave")
    if 'brands' in st.session_state and st.session_state.brands:
        tab_titles.append("🏢 Marcas")
    tabs = st.tabs(tab_titles)
    
    # --- PESTAÑA 1: TRANSCRIPCIÓN ---
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

    # --- PESTAÑA 2: RESUMEN Y CHAT ---
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
                        ans = answer_question(user_q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': user_q, 'answer': ans})
                        st.rerun()
                
                if clear_history:
                    st.session_state.qa_history = []
                    st.rerun()
        else:
            st.info("📝 El resumen no fue generado. Activa la opción en el sidebar y vuelve a transcribir.")
    
    tab_idx = 2
    if 'people' in st.session_state and st.session_state.people:
        with tabs[tab_idx]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            for person in st.session_state.people:
                st.markdown(f"**👤 {person.get('name', 'N/A')}** | **Rol:** *{person.get('role', 'N/A')}*")
                with st.expander("Ver contexto"):
                    st.markdown(f"> {person.get('context', 'N/A')}")
        tab_idx += 1

    if 'brands' in st.session_state and st.session_state.brands:
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
            
            for brand_idx, brand in enumerate(brands_to_show):
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
                        
                        for occurrence_idx, match_idx in enumerate(matches):
                            context_segments = get_extended_context(segments, match_idx, context_lines)
                            
                            for ctx_idx, ctx_seg in enumerate(context_segments):
                                col_time, col_text = st.columns([0.15, 0.85])
                                
                                with col_time:
                                    st.button(
                                        f"▶️ {ctx_seg['time']}", 
                                        key=f"brand_play_{brand_idx}_{occurrence_idx}_{ctx_idx}_{ctx_seg['start']}", 
                                        on_click=set_audio_time, 
                                        args=(ctx_seg['start'],), 
                                        use_container_width=True
                                    )
                                
                                with col_text:
                                    if ctx_seg['is_match']:
                                        pattern = re.compile(re.escape(brand_name), re.IGNORECASE)
                                        highlighted_text = pattern.sub(
                                            f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', 
                                            ctx_seg['text']
                                        )
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
    <p><strong>Transcriptor Pro - Johnascriptor - v4.0.0 PRECISIÓN</strong></p>
    <p style='font-size: 0.9rem;'>🎙️ whisper-large-v3 | 🤖 Post-procesamiento conservador | 🎵 MP3 96kbps</p>
    <p style='font-size: 0.85rem;'>✨ Temperatura 0 + Prompts personalizados + Validación anti-modificación</p>
    <p style='font-size: 0.8rem; margin-top: 0.5rem;'>Desarrollado por Johnathan Cortés</p>
</div>
""", unsafe_allow_html=True)
