import streamlit as st
from groq import Groq, RateLimitError, APIStatusError
import tempfile
import os
import json
import re
import time
import streamlit.components.v1 as components
from datetime import timedelta

# --- CORRECCIÓN: Se mueve el mensaje de error para después del set_page_config ---
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
    from moviepy.audio.fx.all import audio_monize
    MOVIEPY_AVAILABLE = True
except ImportError:
    # Ahora solo establece una bandera. El error se mostrará de forma segura más adelante.
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
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []
if 'entity_search' not in st.session_state: st.session_state.entity_search = ""
if 'entity_filter' not in st.session_state: st.session_state.entity_filter = "Todas"


# --- FUNCIONES CALLBACK ---
def set_audio_time(start_seconds): st.session_state.audio_start_time = int(start_seconds)
def clear_search_callback(): st.session_state.search_input = ""
def clear_entity_search_callback(): st.session_state.entity_search = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit.")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES (Sin cambios) ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1', r'\badministraci(?!ón\b)\b': 'administración', r'\bcomunicaci(?!ón\b)\b': 'comunicación', r'\bdeclaraci(?!ón\b)\b': 'declaración', r'\binformaci(?!ón\b)\b': 'información', r'\borganizaci(?!ón\b)\b': 'organización', r'\bpolític(?!a\b)\b': 'política', r'\bRepúblic(?!a\b)\b': 'República', r'\btecnolog(?!ía\b)\b': 'tecnología', r'\bBogot(?!á\b)\b': 'Bogotá', r'\bMéxic(?!o\b)\b': 'México', r'\bPer\b': 'Perú', r'\btambi(?!én\b)\b': 'también', r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué', r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde', r'\b(M|m)as\b': r'\1ás',
}


# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};
</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    return str(timedelta(seconds=int(seconds)))

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments: return "No se encontraron segmentos."
    return "\n".join([f"[{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}] {s['text'].strip()}" for s in data.segments])

def fix_spanish_encoding(text):
    if not text: return ""
    result = text
    for wrong, correct in {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â\u00bf': '¿', 'Â\u00a1': '¡'}.items():
        result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', lambda m: m.group(1) + m.group(2).upper(), result)
    return (result[0].upper() + result[1:] if result and result[0].islower() else result).strip()

def convert_to_optimized_mp3(file_bytes, filename, target_bitrate='96k'):
    if not MOVIEPY_AVAILABLE:
        return file_bytes, False, "MoviePy no disponible."

    st.info(f"Iniciando estandarización de '{filename}' para la IA...")
    original_size = len(file_bytes) / (1024 * 1024)
    file_ext = os.path.splitext(filename)[1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = tempfile.mktemp(suffix=".mp3")
    
    try:
        audio_clip = None
        try:
            audio_clip = AudioFileClip(input_path)
            st.info("Archivo procesado como audio.")
        except Exception:
            st.warning("No se pudo abrir como audio, intentando como video...")
            video_clip = VideoFileClip(input_path)
            if video_clip.audio is None: raise ValueError("El archivo de video no contiene audio.")
            audio_clip = video_clip.audio
            st.info("Audio extraído del video.")
        
        mono_audio_clip = audio_monize(audio_clip)

        mono_audio_clip.write_audiofile(
            output_path, 
            codec='libmp3lame', 
            bitrate=target_bitrate, 
            fps=16000
        )
        
        mono_audio_clip.close()
        audio_clip.close()

        with open(output_path, 'rb') as f:
            mp3_bytes = f.read()
            
        final_size = len(mp3_bytes) / (1024 * 1024)
        msg = f"✅ Audio estandarizado a 16kHz/Mono: {original_size:.2f} MB → {final_size:.2f} MB"
        return mp3_bytes, True, msg
        
    except Exception as e:
        msg = f"⚠️ Falló la estandarización de audio: **{str(e)}**. Se usará el archivo original."
        return file_bytes, False, msg
        
    finally:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)


# --- FUNCIÓN ROBUSTA PARA LLAMADAS A LA IA ---
def robust_llama_completion(client, messages, model, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(messages=messages, model=model, **kwargs)
            return chat_completion.choices[0].message.content
        except (RateLimitError, APIStatusError) as e:
            if e.status_code in [429, 503] and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                st.warning(f"🤖 Modelo '{model}' sobrecargado. Reintentando en {wait_time}s...")
                time.sleep(wait_time)
            else:
                st.error(f"❌ Error de API persistente con '{model}': {str(e)}")
                return None
        except Exception as e:
            st.error(f"❌ Error inesperado al llamar a la IA: {str(e)}")
            return None
    return None

# --- FUNCIONES DE ANÁLISIS ---
def post_process_with_llama(text, client, model):
    messages = [{"role": "system", "content": "Tu única tarea es corregir tildes y completar palabras comunes en transcripciones (ej. `informaci` -> `información`). No añadas, elimines ni reescribas nada. Devuelve solo el texto corregido."},
                {"role": "user", "content": f"Corrige el siguiente texto:\n\n{text}"}]
    corrected = robust_llama_completion(client, messages, model=model, temperature=0.0, max_tokens=8192)
    return corrected if corrected else text

def generate_summary(text, client, model):
    messages = [{"role": "system", "content": "Eres un experto analista. Crea un resumen ejecutivo conciso (máximo 150 palabras) del texto proporcionado."},
                {"role": "user", "content": f"Resume el siguiente texto:\n\n{text}"}]
    return robust_llama_completion(client, messages, model=model, temperature=0.3, max_tokens=1024) or "No se pudo generar el resumen."

def answer_question(question, text, client, history, model):
    messages = [{"role": "system", "content": "Responde preguntas basándote únicamente en la transcripción. Si la respuesta no está en el texto, indícalo claramente."}]
    for qa in history: messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
    messages.append({"role": "user", "content": f"Transcripción:\n---\n{text}\n---\nPregunta: {question}"})
    return robust_llama_completion(client, messages, model=model, temperature=0.2, max_tokens=2048) or "No se pudo procesar la pregunta."

def extract_all_entities(text, client, model):
    messages = [
        {"role": "system", "content": """
Eres un sistema de extracción de entidades (NER) de alta precisión. Analiza el texto y extrae TODAS las entidades mencionadas, clasificándolas en las siguientes categorías: 'Persona', 'Organización', 'Lugar', 'Marca', 'Cargo'.
REGLAS ESTRICTAS:
1.  **CATEGORÍAS:**
    -   **Persona:** Nombres de individuos (ej. "Juan Pérez").
    -   **Organización:** Nombres de empresas, hospitales, universidades, etc. (ej. "Hospital General", "Google").
    -   **Lugar:** Nombres de ciudades, países (ej. "Bogotá").
    -   **Marca:** Nombres de productos comerciales (ej. "iPhone").
    -   **Cargo:** Títulos profesionales (ej. "presidente", "doctor").
2.  **FORMATO OBLIGATORIO:** Responde únicamente con un objeto JSON. La clave principal DEBE ser "entidades". Cada objeto en la lista DEBE usar las claves en inglés: "name", "category", y "context".
    Ejemplo de formato:
    {
      "entidades": [
        { "name": "Dr. Carlos Rivas", "category": "Persona", "context": "El Dr. Carlos Rivas mencionó los avances." }
      ]
    }
3.  Si no encuentras entidades, devuelve: {"entidades": []}
"""},
        {"role": "user", "content": f"Extrae todas las entidades del siguiente texto:\n\n{text[:8000]}"}
    ]
    response_json_str = robust_llama_completion(client, messages, model=model, temperature=0.0, max_tokens=4096, response_format={"type": "json_object"})
    if not response_json_str: return []
    try:
        data = json.loads(response_json_str)
        validated_entities = []
        for entity in data.get('entidades', []):
            name = entity.get('name') or entity.get('nombre')
            category = entity.get('category') or entity.get('categoría')
            context = entity.get('context') or entity.get('contexto')
            if name and category:
                validated_entities.append({'name': name, 'category': category, 'context': context})
        return validated_entities
    except (json.JSONDecodeError, TypeError):
        return []

# --- FUNCIONES DE EXPORTACIÓN Y BÚSQUEDA ---
def get_extended_context(segments, match_index, context_range=2):
    start_idx, end_idx = max(0, match_index - context_range), min(len(segments), match_index + context_range + 1)
    return [{'text': s['text'].strip(), 'time': format_timestamp(s['start']), 'start': s['start'], 'is_match': (i == match_index)} for i, s in enumerate(segments) if start_idx <= i < end_idx]

def export_to_srt(data):
    srt_lines = []
    for i, seg in enumerate(data.segments, 1):
        start = timedelta(seconds=seg['start']); end = timedelta(seconds=seg['end'])
        start_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt_lines.append(f"{i}\n{start_str} --> {end_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt_lines)

def find_entity_in_segments(entity_name, segments):
    matches = []
    pattern = re.compile(r'\b' + re.escape(entity_name) + r'\b', re.IGNORECASE)
    for i, seg in enumerate(segments):
        if pattern.search(seg['text']): matches.append(i)
    return matches

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo de Transcripción", ["whisper-large-v3"])
    language = st.selectbox("Idioma del Audio", ["es"])
    
    st.markdown("---")
    st.subheader("🤖 Análisis con IA")
    llama_model_option = st.selectbox("Modelo de Llama para Análisis", ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"], help="Elige 'instant' para velocidad o 'versatile' para máxima calidad.")
    
    enable_llama_postprocess = st.checkbox("Corrección IA de la transcripción", value=True)
    enable_summary = st.checkbox("📝 Generar resumen ejecutivo", value=True)
    enable_entities = st.checkbox("📊 Extraer Entidades", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    
    st.markdown("---")
    # --- CORRECCIÓN: Mostrar el error aquí, de forma segura ---
    if MOVIEPY_AVAILABLE:
        st.success("✅ **Estandarización de Audio Activada:** Convierte todo a formato ideal para la IA (16kHz, Mono).")
    else:
        st.error("Librería `moviepy` no encontrada. La conversión de audio no funcionará.")
        st.warning("Añade `moviepy` y `imageio-ffmpeg` a tu archivo `requirements.txt`.")

st.subheader("📤 Sube tu archivo de audio o video")
uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "avi", "mov"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    for key in list(st.session_state.keys()):
        if key not in ['password_correct', 'password_attempted']: del st.session_state[key]
    st.session_state.qa_history = []
    
    try:
        file_bytes = uploaded_file.getvalue()
        
        with st.spinner("🔄 Estandarizando audio para máxima precisión..."):
            processed_bytes, was_converted, conv_message = convert_to_optimized_mp3(file_bytes, uploaded_file.name)
            st.info(conv_message)
        st.session_state.uploaded_audio_bytes = processed_bytes
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
            tmp.write(processed_bytes)
            tmp_path = tmp.name
        
        with st.spinner("🔄 Transcribiendo con IA (máxima precisión)..."):
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(uploaded_file.name, audio_file.read()), 
                    model=model_option, language=language,
                    response_format="verbose_json", temperature=0.1
                )
        os.unlink(tmp_path)
        
        text = fix_spanish_encoding(transcription.text)
        if enable_llama_postprocess:
            with st.spinner("🤖 Mejorando transcripción con IA..."):
                text = post_process_with_llama(text, client, llama_model_option)
        
        for seg in transcription.segments:
            seg['text'] = fix_spanish_encoding(seg['text'])
        
        st.session_state.transcription = text
        st.session_state.transcription_data = transcription
        
        with st.spinner("🧠 Generando análisis avanzado..."):
            if enable_summary: st.session_state.summary = generate_summary(text, client, llama_model_option)
            if enable_entities: st.session_state.entities = extract_all_entities(text, client, llama_model_option)
        
        st.success("✅ ¡Proceso completado!")
        st.balloons()
        st.rerun()
    except Exception as e:
        st.error(f"❌ Error crítico: {e}")

# --- SECCIÓN DE RESULTADOS ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo"]
    if 'entities' in st.session_state and st.session_state.get('entities'):
        tab_titles.append("📊 Entidades Clave")
    tabs = st.tabs(tab_titles)
    
    # Pestaña 1: Transcripción
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color: #FFD700; color: black; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        MATCH_STYLE = "background-color: #1a1a2e; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #fca311;"
        CONTEXT_STYLE = "background-color: #1f1f1f; padding: 0.6rem; border-radius: 4px;"
        BOX_STYLE = "background-color: #000000; color: #FFFFFF; border: 1px solid #444; border-radius: 10px; padding: 1.5rem; height: 500px; overflow-y: auto; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; line-height: 1.75; font-size: 1rem;"
        
        c1, c2 = st.columns([4, 1])
        search_query = c1.text_input("🔎 Buscar en la transcripción:", key="search_input")
        if search_query: c2.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True)

        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments, pattern = st.session_state.transcription_data.segments, re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if matches:
                    st.success(f"✅ {len(matches)} coincidencia(s) encontrada(s).")
                    for match_idx in matches:
                        for ctx in get_extended_context(segments, match_idx, context_lines):
                            ct, cc = st.columns([0.15, 0.85])
                            ct.button(f"▶️ {ctx['time']}", key=f"play_{match_idx}_{ctx['start']}", on_click=set_audio_time, args=(ctx['start'],), use_container_width=True)
                            text_html = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx['text']) if ctx['is_match'] else ctx['text']
                            cc.markdown(f"<div style='color: white; {MATCH_STYLE if ctx['is_match'] else CONTEXT_STYLE}'>{text_html}</div>", unsafe_allow_html=True)
                        st.markdown("---")
                else: st.info("❌ No se encontraron coincidencias.")
        
        html = re.sub(f"({re.escape(search_query)})", f'<span style="{HIGHLIGHT_STYLE}">\g<1></span>', st.session_state.transcription, flags=re.IGNORECASE) if search_query else st.session_state.transcription
        st.markdown(f'<div style="{BOX_STYLE}">{html.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        c1.download_button("💾 TXT", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", use_container_width=True)
        c3.download_button("💾 SRT", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    # Pestaña 2: Resumen
    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            st.markdown("---")
            st.markdown("### 💭 Pregunta sobre el contenido")
            
            for qa in st.session_state.qa_history:
                with st.chat_message("user"): st.markdown(qa['question'])
                with st.chat_message("assistant"): st.markdown(qa['answer'])

            if user_q := st.chat_input("Escribe tu pregunta aquí..."):
                with st.spinner("🤔 Analizando..."):
                    ans = answer_question(user_q, st.session_state.transcription, client, st.session_state.qa_history, llama_model_option)
                    st.session_state.qa_history.append({'question': user_q, 'answer': ans})
                    st.rerun()
        else: st.info("El resumen no fue generado.")

    # Pestaña 3: Entidades
    if 'entities' in st.session_state and st.session_state.get('entities'):
        with tabs[2]:
            st.markdown("### 📊 Entidades Clave Identificadas")
            entities = st.session_state.entities
            
            categories = ["Todas"] + sorted(list(set(e.get('category', 'N/A') for e in entities)))
            
            c1, c2, c3 = st.columns([2, 2, 1])
            selected_category = c1.selectbox("Filtrar por categoría:", options=categories, key="entity_filter")
            entity_search_query = c2.text_input("Buscar entidad por nombre:", key="entity_search")
            if entity_search_query: c3.button("🗑️", on_click=clear_entity_search_callback, key="clear_entity_btn")

            filtered_entities = entities
            if selected_category != "Todas":
                filtered_entities = [e for e in filtered_entities if e.get('category') == selected_category]
            if entity_search_query:
                pattern = re.compile(re.escape(entity_search_query), re.IGNORECASE)
                filtered_entities = [e for e in filtered_entities if pattern.search(e.get('name', ''))]

            if not filtered_entities:
                st.info("No se encontraron entidades con los filtros seleccionados.")
            else:
                st.success(f"Mostrando {len(filtered_entities)} de {len(entities)} entidades totales.")
                for entity in filtered_entities:
                    entity_name, entity_cat = entity.get('name'), entity.get('category')
                    st.markdown(f"**{entity_name}** | **Categoría:** `{entity_cat}`")
                    
                    with st.expander("Ver contexto y menciones en audio"):
                        st.markdown(f"> {entity.get('context', 'Sin contexto.')}")
                        segments = st.session_state.transcription_data.segments
                        matches = find_entity_in_segments(entity_name, segments)
                        if matches:
                            st.markdown(f"**📍 {len(matches)} mención(es) encontrada(s):**")
                            for match_idx in matches:
                                st.markdown("---")
                                for ctx in get_extended_context(segments, match_idx, context_lines):
                                    ct, cc = st.columns([0.15, 0.85])
                                    ct.button(f"▶️ {ctx['time']}", key=f"entity_play_{entity_name}_{match_idx}_{ctx['start']}", on_click=set_audio_time, args=(ctx['start'],), use_container_width=True)
                                    text_html = re.sub(f'({re.escape(entity_name)})', f'<span style="{HIGHLIGHT_STYLE}">\g<1></span>', ctx['text'], flags=re.IGNORECASE) if ctx['is_match'] else ctx['text']
                                    cc.markdown(f"<div style='color: white; {MATCH_STYLE if ctx['is_match'] else CONTEXT_STYLE}'>{text_html}</div>", unsafe_allow_html=True)
                        else:
                            st.info("No se encontraron menciones exactas en los segmentos de la transcripción.")

# --- Pie de página y Limpieza ---
st.markdown("---")
if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
    pwd_ok = st.session_state.get('password_correct', False)
    st.session_state.clear()
    st.session_state.password_correct = pwd_ok
    st.rerun()

st.markdown("""
<div style='text-align: center; color: #666; margin-top: 2rem;'>
    <p><strong>Transcriptor Pro - Johnascriptor - v4.5.0 (Final Stable)</strong></p>
    <p style='font-size: 0.9rem;'>🎙️ whisper-large-v3 | 🤖 Llama 3.1 & 3.3 | 🎵 Conversión a Mono Estable | 📊 NER Robusto</p>
</div>
""", unsafe_allow_html=True)
