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

# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

# --- FUNCIÓN CALLBACK PARA LIMPIAR BÚSQUEDA ---
def clear_search_callback():
    st.session_state.search_input = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES ---
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
        with open(audio_path, 'rb') as f: audio_bytes = f.read()
        os.unlink(video_path); os.unlink(audio_path)
        return audio_bytes, True
    except Exception: return video_bytes, False

def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIÓN DE POST-PROCESAMIENTO CON IA ---
def post_process_with_llama(transcription_text, client):
    # Esta función ahora puede recibir segmentos pequeños o el texto completo
    if not transcription_text or not transcription_text.strip():
        return transcription_text
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": """Eres un micro-servicio de corrección de texto, no un editor. Tu comportamiento es estrictamente reglado.

**REGLAS INVIOLABLES:**
1.  **ACENTUACIÓN PRECISA:** Tu tarea principal es añadir tildes faltantes a palabras que inequívocamente las requieren (ej: `como` -> `cómo`, `esta` -> `está`, `mas` -> `más`).
2.  **COMPLETAR PALABRAS:** Únicamente completarás palabras con terminaciones obvias y comunes en transcripciones (ej: `informaci` -> `información`, `tecnolog` -> `tecnología`).
3.  **NO CAMBIAR PALABRAS VÁLIDAS:** Si una palabra ya es correcta y existe en el diccionario español, NO la modificarás bajo ninguna circunstancia.
4.  **PROHIBIDO INVENTAR, OMITIR O REESCRIBIR:** No puedes añadir, eliminar ni cambiar el orden de las palabras. No puedes reescribir frases.
5.  **DEVOLVER TEXTO ÍNTEGRO:** Siempre devolverás el texto completo, aplicando únicamente las correcciones permitidas.

Tu salida debe ser únicamente el texto corregido."""},
                {"role": "user", "content": f"Aplica tus reglas de corrección a la siguiente transcripción. No alteres nada más:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.0, # Temperatura CERO para máxima precisión y predictibilidad
            max_tokens=4096
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"⚠️ No se pudo aplicar post-procesamiento con IA: {str(e)}")
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
    except Exception as e: return f"Error al generar resumen: {str(e)}"

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
    except Exception as e: return f"Error al procesar la pregunta: {str(e)}"

def extract_people_and_roles(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": '''Eres un analista de inteligencia de alta precisión. Tu tarea es identificar CADA persona mencionada por su nombre completo en la transcripción y su rol o cargo si se especifica.

REGLAS ESTRICTAS:
1.  **SOLO PERSONAS**: Extrae únicamente nombres de individuos (ej: "Juan Pérez"). NO extraigas nombres de organizaciones.
2.  **ROL EXACTO**: Si se menciona un cargo (ej: "presidente"), captúralo. Si no, usa "No especificado". No inventes roles.
3.  **CONTEXTO PRECISO**: El contexto es la frase exacta donde se menciona a la persona.
4.  **FORMATO JSON OBLIGATORIO**: La salida debe ser un objeto JSON válido con una clave "personas".'''},
                {"role": "user", "content": f"Analiza la siguiente transcripción y extrae las personas y sus roles según tus reglas. Devuelve solo el JSON:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.0, max_tokens=1500, response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        return data.get('personas', [])
    except Exception as e:
        return [{"name": "Error de Análisis", "role": str(e), "context": "No se pudo procesar la respuesta de la IA."}]

def extract_brands_and_entities(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": '''Eres un analista de inteligencia de alta precisión. Tu tarea es identificar CADA marca comercial, empresa, organización o institución mencionada en el texto.

REGLAS ESTRICTAS:
1.  **SOLO ORGANIZACIONES**: Extrae únicamente nombres de entidades (ej: "Google", "Ministerio de Educación"). NO extraigas nombres de personas.
2.  **TIPO DE ENTIDAD**: Clasifica la entidad como "Empresa", "Institución", "ONG", "Marca", etc.
3.  **CONTEXTO PRECISO**: El contexto es la frase exacta donde se menciona la entidad.
4.  **FORMATO JSON OBLIGATORIO**: La salida debe ser un objeto JSON válido con una clave "entidades".'''},
                {"role": "user", "content": f"Analiza la siguiente transcripción y extrae las marcas y organizaciones según tus reglas. Devuelve solo el JSON:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.0, max_tokens=1500, response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        return data.get('entidades', [])
    except Exception as e:
        return [{"name": "Error de Análisis", "type": str(e), "context": "No se pudo procesar la respuesta de la IA."}]

def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    context_segments = [{'text': segments[i]['text'].strip(), 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start_idx, end_idx)]
    return context_segments

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start_time = timedelta(seconds=seg['start']); end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo de Transcripción", ["whisper-large-v3"], help="Máxima precisión para español.")
    language = st.selectbox("Idioma", ["es"], help="Español para máxima calidad de corrección.")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_llama_postprocess = st.checkbox("🤖 Post-procesamiento IA", value=True, help="Usa Llama-3.1 para corregir tildes y palabras cortadas.")
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_people = st.checkbox("👥 Extraer personas y cargos", value=True)
    enable_brands = st.checkbox("🏢 Extraer marcas", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2, help="Líneas antes y después del resultado.")
    
    st.markdown("---")
    if MOVIEPY_AVAILABLE:
        st.info("💡 MP4 > 25 MB se convertirán a audio.")
    st.info("💡 Formatos: MP3, MP4, WAV, M4A, etc.")
    st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        for key in list(st.session_state.keys()):
            if key not in ['password_correct', 'password_attempted']:
                del st.session_state[key]
        
        st.session_state.audio_start_time = 0
        st.session_state.qa_history = []
        
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                if os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4', '.mpeg', '.webm'] and MOVIEPY_AVAILABLE and get_file_size_mb(file_bytes) > 25:
                    with st.spinner("🎬 Convirtiendo video a audio..."):
                        file_bytes, _ = convert_video_to_audio(file_bytes, uploaded_file.name)
                
                st.session_state.uploaded_audio_bytes = file_bytes
                client = Groq(api_key=api_key)
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_file_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA (modo de máxima precisión)..."):
                    with open(tmp_file_path, "rb") as audio_file:
                        spanish_prompt = (
                            "Esta es una transcripción profesional que requiere la máxima precisión. Transcribe absolutamente todo el audio de forma literal. "
                            "No omitas ninguna palabra, frase o segmento, incluso si el audio es poco claro o hay ruido de fondo. "
                            "Tu objetivo es la exhaustividad total. No resumas ni omitas NADA."
                        )

                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model=model_option,
                            language=language,
                            response_format="verbose_json",
                            prompt=spanish_prompt,
                            temperature=0.0
                        )
                os.unlink(tmp_file_path)

                # --- MODIFICACIÓN CLAVE: PROCESAR CADA SEGMENTO ---
                # Ahora procesamos cada segmento individualmente para que la búsqueda
                # y la transcripción completa usen el mismo texto limpio.
                progress_text = "🤖 Mejorando transcripción con IA..." if enable_llama_postprocess else "🧹 Limpiando transcripción..."
                with st.spinner(progress_text):
                    # Usamos una barra de progreso para dar feedback al usuario
                    progress_bar = st.progress(0, text=f"Procesando segmento 0/{len(transcription.segments)}")
                    
                    for i, seg in enumerate(transcription.segments):
                        # 1. Aplicar la corrección de codificación y reglas básicas
                        cleaned_text = fix_spanish_encoding(seg['text'])
                        
                        # 2. Si está habilitado, aplicar el post-procesamiento con IA
                        if enable_llama_postprocess:
                            cleaned_text = post_process_with_llama(cleaned_text, client)
                        
                        # 3. Actualizar el texto del segmento con la versión limpia
                        seg['text'] = cleaned_text
                        
                        # Actualizar la barra de progreso
                        progress_bar.progress((i + 1) / len(transcription.segments), text=f"Procesando segmento {i+1}/{len(transcription.segments)}")

                # --- MODIFICACIÓN CLAVE: CONSTRUIR EL TEXTO COMPLETO DESDE LOS SEGMENTOS LIMPIOS ---
                # La transcripción completa ahora es la unión de los segmentos ya procesados.
                transcription_text = "\n".join([seg['text'].strip() for seg in transcription.segments])
                
                # Almacenar los datos procesados en el estado de la sesión
                st.session_state.transcription = transcription_text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis..."):
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
                st.error(f"❌ Error durante la transcripción: {e}")


if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo"]
    if 'people' in st.session_state and st.session_state.people: tab_titles.append("👥 Personas Clave")
    if 'brands' in st.session_state and st.session_state.brands: tab_titles.append("🏢 Marcas")
    
    tabs = st.tabs(tab_titles)
    
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        MATCH_LINE_STYLE = "background-color: #1e3a5f; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #fca311; color: #ffffff;"
        CONTEXT_LINE_STYLE = "background-color: #1a1a1a; padding: 0.6rem; border-radius: 4px; color: #b8b8b8;"
        TRANSCRIPTION_BOX_STYLE = "background-color: #0E1117; color: #FAFAFA; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; line-height: 1.7; white-space: pre-wrap; font-size: 0.95rem;"

        col_search1, col_search2 = st.columns([4, 1])
        with col_search1:
            search_query = st.text_input("🔎 Buscar en la transcripción:", key="search_input")
        with col_search2:
            st.write("")
            st.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True, disabled=not search_query)

        # Ahora la búsqueda ya opera sobre los segmentos limpios, por lo que será consistente.
        if search_query:
            with st.expander("📍 Resultados de búsqueda con contexto", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                
                if not matching_indices:
                    st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s).")
                    for result_num, match_idx in enumerate(matching_indices, 1):
                        context_segments = get_extended_context(segments, match_idx, context_lines)
                        for ctx_seg in context_segments:
                            col_time, col_content = st.columns([0.15, 0.85])
                            with col_time:
                                st.button(f"▶️ {ctx_seg['time']}", key=f"play_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                            with col_content:
                                style = MATCH_LINE_STYLE if ctx_seg['is_match'] else CONTEXT_LINE_STYLE
                                highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx_seg['text']) if ctx_seg['is_match'] else ctx_seg['text']
                                st.markdown(f"<div style='{style}'>{highlighted_text}</div>", unsafe_allow_html=True)
                        if result_num < len(matching_indices): st.markdown("---")
        
        st.markdown("📄 Transcripción completa:")
        transcription_html = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            transcription_html = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', transcription_html)
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{transcription_html}</div>', unsafe_allow_html=True)
        
        st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1: st.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        with col_d2: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", use_container_width=True)
        with col_d3: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with col_d4: create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            
            st.markdown("---")
            st.markdown("### 💭 Haz preguntas sobre el contenido")
            st.caption("Obtén respuestas basadas en la transcripción completa.")
            
            if 'qa_history' not in st.session_state: st.session_state.qa_history = []
            
            if st.session_state.qa_history:
                st.markdown("#### 📚 Historial de conversación")
                for i, qa in enumerate(st.session_state.qa_history):
                    st.markdown(f"**Pregunta {i+1}:** {qa['question']}")
                    st.markdown(f"**Respuesta:** {qa['answer']}")
                    st.markdown("---")
            
            with st.form(key="question_form", clear_on_submit=True):
                user_question = st.text_area("Escribe tu pregunta aquí:", height=100)
                submit_q, clear_h = st.columns(2)
                with submit_q:
                    submit_question = st.form_submit_button("🚀 Enviar Pregunta", use_container_width=True)
                with clear_h:
                    clear_history = st.form_submit_button("🗑️ Borrar Historial", use_container_width=True)

                if submit_question and user_question.strip():
                    with st.spinner("🤔 Analizando..."):
                        client = Groq(api_key=api_key)
                        answer = answer_question(user_question, st.session_state.transcription, client, st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': user_question, 'answer': answer})
                        st.rerun()
                
                if clear_history:
                    st.session_state.qa_history = []
                    st.rerun()
        else:
            st.info("📝 El resumen no fue generado. Activa la opción en el sidebar y vuelve a transcribir.")
    
    tab_index = 2
    if 'people' in st.session_state and st.session_state.people:
        with tabs[tab_index]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            people_data = st.session_state.people
            if people_data and "Error" not in people_data[0].get('name', ''):
                for person in people_data:
                    st.markdown(f"**👤 {person.get('name', 'N/A')}** | **Rol:** *{person.get('role', 'N/A')}*")
                    with st.expander("Ver contexto"): st.markdown(f"> {person.get('context', 'N/A')}")
            else: st.info("👤 No se identificaron personas o hubo un error en el análisis.")
        tab_index += 1

    if 'brands' in st.session_state and st.session_state.brands:
        with tabs[tab_index]:
            st.markdown("### 🏢 Marcas y Organizaciones Mencionadas")
            brands_data = st.session_state.brands
            if brands_data and "Error" not in brands_data[0].get('name', ''):
                for brand in brands_data:
                    st.markdown(f"**🏢 {brand.get('name', 'N/A')}** | **Tipo:** *{brand.get('type', 'N/A')}*")
                    with st.expander("Ver contexto"): st.markdown(f"> {brand.get('context', 'N/A')}")
            else: st.info("🏢 No se identificaron marcas o hubo un error en el análisis.")

# --- Pie de página y Limpieza ---
st.markdown("---")
if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
    password_correct = st.session_state.get('password_correct', False)
    st.session_state.clear()
    st.session_state.password_correct = password_correct
    st.rerun()

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p><strong>Transcriptor Pro - Johnascriptor - v3.2.1 (Modelo whisper-large-v3 | llama-3.1-8b-instant)</strong> - Desarrollado por Johnathan Cortés 🤖</p>
    <p style='font-size: 0.85rem;'>✨ Con sistema de post-procesamiento IA, corrección mejorada y análisis de marcas</p>
</div>
""", unsafe_allow_html=True)
