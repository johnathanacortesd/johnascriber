import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta

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
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA para noticias.</p>
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
if 'transcription_id' not in st.session_state: st.session_state.transcription_id = 0
if 'search_counter' not in st.session_state: st.session_state.search_counter = 0
if 'last_search' not in st.session_state: st.session_state.last_search = ""
if 'qa_history' not in st.session_state: st.session_state.qa_history = []


# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES ---
SPANISH_WORD_CORRECTIONS = {
    r'\b([A-Za-z]+)ci(?!ón\b)\b': r'\1ción', r'\b([A-Za-z]+)cr(?!ítica\b)\b': r'\1crítica', r'\b([A-Za-z]+)t(?!ico\b)\b': r'\1tico', r'\b([A-Za-z]+)g(?!ía\b)\b': r'\1gía', r'\b([A-Za-z]+)mic(?!a\b)\b': r'\1mica', r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1', r'\bRepúblic(?!a\b)\b': 'República', r'\brepúblic(?!a\b)\b': 'república', r'\bBogot(?!á\b)\b': 'Bogotá', r'\bpolític(?!a\b)\b': 'política', r'\bPolític(?!a\b)\b': 'Política', r'\beconómic(?!a\b)\b': 'económica', r'\bEconómic(?!a\b)\b': 'Económica', r'\bAméric(?!a\b)\b': 'América', r'\badem(?!ás\b)\b': 'además', r'\bAdem(?!ás\b)\b': 'Además', r'\btambi(?!én\b)\b': 'también', r'\bTambi(?!én\b)\b': 'También', r'\búltim(?!o\b)\b': 'último', r'\bÚltim(?!o\b)\b': 'Último', r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué', r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde', r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES ---

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    components.html(f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};</script>""", height=40)

def format_timestamp(seconds):
    return str(timedelta(seconds=int(seconds)))

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments: return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    encoding_fixes = {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã‘': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for wrong, correct in encoding_fixes.items(): result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items(): result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result.strip()

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start_time = timedelta(seconds=seg['start']); end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds // 3600:02}:{(start_time.seconds // 60) % 60:02}:{start_time.seconds % 60:02},{start_time.microseconds // 1000:03}"
        end = f"{end_time.seconds // 3600:02}:{(end_time.seconds // 60) % 60:02}:{end_time.seconds % 60:02},{end_time.microseconds // 1000:03}"
        text = seg['text'].strip()
        srt_content.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(srt_content)

def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    context_segments = []
    for i in range(start_idx, end_idx):
        seg = segments[i]; is_match = (i == match_index)
        context_segments.append({'text': seg['text'].strip(), 'time': format_timestamp(seg['start']), 'start': seg['start'], 'is_match': is_match})
    return context_segments

# --- FUNCIONES DE CONVERSIÓN Y PROCESAMIENTO ---

def process_uploaded_file(uploaded_file):
    file_bytes = uploaded_file.getvalue(); original_size = len(file_bytes) / (1024 * 1024); file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    if file_extension in ['.mp4', '.mpeg', '.webm'] and MOVIEPY_AVAILABLE and original_size > 25:
        with st.spinner(f"🎬 Video detectado ({original_size:.2f} MB). Convirtiendo a audio..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_video: tmp_video.write(file_bytes); video_path = tmp_video.name
            audio_path = video_path + '.mp3'
            try:
                video = VideoFileClip(video_path); video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None); video.close()
                with open(audio_path, 'rb') as f: file_bytes = f.read()
                st.success(f"✅ Conversión completa: {original_size:.2f} MB → {len(file_bytes) / (1024 * 1024):.2f} MB")
            except Exception as e: st.warning(f"⚠️ No se pudo convertir el video. Se intentará transcribir directamente. Error: {e}")
            finally:
                if os.path.exists(video_path): os.unlink(video_path)
                if os.path.exists(audio_path): os.unlink(audio_path)
    return file_bytes

# --- FUNCIONES DE ANÁLISIS CON IA ---

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un analista de noticias experto. Tu tarea es crear un resumen ejecutivo, conciso y profesional en un solo párrafo. Regla estricta: NO incluyas frases introductorias como 'A continuación se presenta un resumen' o 'El texto trata sobre'. Comienza directamente con el contenido del resumen. Utiliza español correcto con todas sus tildes."},
                {"role": "user", "content": f"Genera un resumen ejecutivo en un párrafo (máximo 150 palabras) de la siguiente transcripción. Empieza directamente con la información, sin preámbulos.\n\nTranscripción:\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

# --- FUNCIÓN DE CHAT RESTAURADA ---
def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Eres un asistente experto en análisis de contenido. Responde preguntas sobre la transcripción proporcionada de manera precisa, concisa y profesional. Basa tus respuestas ÚNICAMENTE en la transcripción. Si la información no está, indícalo claramente. Considera el contexto de la conversación anterior."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Transcripción completa del audio:\n---\n{transcription_text}\n---\nPregunta: {question}\nResponde basándote exclusivamente en la transcripción."})
        chat_completion = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant", temperature=0.2, max_tokens=800)
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

def extract_entities(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": 'Eres un analista experto en noticias de Colombia. Tu tarea es identificar personas, sus cargos y marcas mencionadas. Devuelve un objeto JSON con dos claves: "people" y "brands".\n- "people": una lista de objetos, cada uno con "name", "role" y "context" (la frase exacta).\n- "brands": una lista de objetos, cada uno con "name" y "context".\nSi no encuentras nada, devuelve listas vacías. El JSON debe ser válido.'},
                {"role": "user", "content": f"Analiza esta transcripción y extrae las personas, cargos y marcas. Formatea la salida como el JSON especificado.\n\nTranscripción:\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.1, max_tokens=1500, response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        return data.get("people", []), data.get("brands", [])
    except (json.JSONDecodeError, KeyError) as e: return [{"name": "Error de Análisis", "role": "La IA no devolvió un JSON válido.", "context": str(e)}], []
    except Exception as e: return [{"name": "Error de API", "role": str(e), "context": "No se pudo contactar al servicio de análisis."}], []

def enrich_entities_with_timestamps(entities, segments):
    enriched_entities = {}
    for entity in entities:
        entity_name = entity.get("name", "Desconocido").strip()
        if not entity_name: continue
        if entity_name not in enriched_entities: enriched_entities[entity_name] = {"details": entity, "mentions": []}
        for segment in segments:
            if re.search(r'\b' + re.escape(entity_name) + r'\b', segment['text'], re.IGNORECASE):
                enriched_entities[entity_name]["mentions"].append({"start": segment['start'], "time": format_timestamp(segment['start']), "context": segment['text'].strip()})
    for name in enriched_entities:
        unique_mentions = list({v['start']:v for v in enriched_entities[name]['mentions']}.values())
        enriched_entities[name]['mentions'] = sorted(unique_mentions, key=lambda x: x['start'])
    return enriched_entities

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración"); model_option = st.selectbox("Modelo", ["whisper-large-v3"], help="Máxima precisión para español."); language = st.selectbox("Idioma", ["es"], help="Español para máxima calidad de corrección."); temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0.0 para máxima precisión"); st.markdown("---"); st.subheader("🎯 Análisis Inteligente"); enable_summary = st.checkbox("📝 Generar resumen", value=True); enable_entities = st.checkbox("👥 Extraer personas y marcas", value=True); st.markdown("---"); st.subheader("🔍 Búsqueda Contextual"); context_lines = st.slider("Líneas de contexto", 1, 5, 2); st.markdown("---"); 
    if MOVIEPY_AVAILABLE: st.info("💡 Videos > 25 MB se convertirán a audio.");
    else: st.warning("⚠️ MoviePy no disponible para conversión.");
    st.markdown("---"); st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    for key in list(st.session_state.keys()):
        if key not in ['password_correct', 'password_attempted']: st.session_state.pop(key)
    st.session_state.audio_start_time = 0; st.session_state.transcription_id += 1; st.session_state.last_search = ""; st.session_state.qa_history = []
    
    file_bytes = process_uploaded_file(uploaded_file)
    st.session_state.uploaded_audio_bytes = file_bytes
    
    try:
        client = Groq(api_key=api_key);
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp: tmp.write(file_bytes); tmp_path = tmp.name
        
        with st.spinner("🔄 Transcribiendo con IA..."):
            with open(tmp_path, "rb") as audio_file:
                spanish_prompt = "Este es un noticiero de Colombia. Transcribe con la máxima precisión posible en español colombiano. Reglas estrictas: 1. NUNCA cortes palabras, especialmente las que llevan tilde como 'política', 'económica', 'República', 'autocrítica'. Escríbelas completas. 2. Pon especial atención a las tildes en preguntas (qué, cómo, cuándo) y en palabras como 'sí' (afirmación), 'más' (cantidad), 'está' (verbo). 3. Mantén la puntuación original. 4. Transcribe nombres propios y acrónimos fielmente."
                transcription = client.audio.transcriptions.create(file=(uploaded_file.name, audio_file.read()), model=model_option, temperature=temperature, language=language, response_format="verbose_json", prompt=spanish_prompt)
        os.unlink(tmp_path)
        
        with st.spinner("✨ Aplicando correcciones..."):
            transcription_text = fix_spanish_encoding(transcription.text)
            for segment in transcription.segments: segment['text'] = fix_spanish_encoding(segment['text'])
        
        st.session_state.transcription = transcription_text; st.session_state.transcription_data = transcription
        
        with st.spinner("🧠 Generando análisis..."):
            if enable_summary: st.session_state.summary = generate_summary(transcription_text, client)
            if enable_entities:
                people, brands = extract_entities(transcription_text, client)
                st.session_state.people = enrich_entities_with_timestamps(people, transcription.segments)
                st.session_state.brands = enrich_entities_with_timestamps(brands, transcription.segments)

        st.success("✅ ¡Proceso completado!"); st.balloons()
    except Exception as e: st.error(f"❌ Error durante la transcripción: {e}")

if 'transcription' in st.session_state:
    st.markdown("---"); st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)

    tab_titles = ["📝 Transcripción Completa", "📊 Resumen Interactivo"]
    if enable_entities: tab_titles.append("👥 Entidades Clave")
    tabs = st.tabs(tab_titles)

    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"; MATCH_LINE_STYLE = "background-color: #1e3a5f; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #fca311; color: #ffffff;"; CONTEXT_LINE_STYLE = "background-color: #1a1a1a; padding: 0.6rem; border-radius: 4px; color: #b8b8b8; border-left: 2px solid #404040;"; TRANSCRIPTION_BOX_STYLE = "background-color: #0E1117; color: #FAFAFA; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; white-space: pre-wrap;"
        
        col_search1, col_search2 = st.columns([4, 1])
        with col_search1:
            search_query = st.text_input("🔎 Buscar en la transcripción:", value=st.session_state.last_search, key=f"search_input_{st.session_state.search_counter}")
            if search_query != st.session_state.last_search: st.session_state.last_search = search_query
        with col_search2:
            st.write("");
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query): st.session_state.last_search = ""; st.session_state.search_counter += 1; st.rerun()
        
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments; pattern = re.compile(re.escape(search_query), re.IGNORECASE); matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if not matching_indices: st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)");
                    for result_num, match_idx in enumerate(matching_indices, 1):
                        context_segments = get_extended_context(segments, match_idx, context_lines)
                        for ctx_seg in context_segments:
                            col_time, col_content = st.columns([0.15, 0.85]);
                            with col_time: st.button(f"▶️ {ctx_seg['time']}", key=f"play_ctx_{result_num}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                            with col_content:
                                if ctx_seg['is_match']: highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', ctx_seg['text']); st.markdown(f"<div style='{MATCH_LINE_STYLE}'><strong>🎯 </strong>{highlighted_text}</div>", unsafe_allow_html=True)
                                else: st.markdown(f"<div style='{CONTEXT_LINE_STYLE}'>{ctx_seg['text']}</div>", unsafe_allow_html=True)
                        if result_num < len(matching_indices): st.markdown("---")
        
        st.markdown("**📄 Transcripción completa:**"); transcription_html = st.session_state.transcription.replace('\n', '<br>')
        if search_query: pattern = re.compile(re.escape(search_query), re.IGNORECASE); transcription_html = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', transcription_html)
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}" key="transcription_box_{st.session_state.transcription_id}">{transcription_html}</div>', unsafe_allow_html=True); st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5]);
        with col_d1: st.download_button("💾 TXT Simple", st.session_state.transcription.encode('utf-8'), "transcripcion.txt", use_container_width=True)
        with col_d2: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data).encode('utf-8'), "tiempos.txt", use_container_width=True)
        with col_d3: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data).encode('utf-8'), "subtitulos.srt", use_container_width=True)
        with col_d4: create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo"); st.markdown(st.session_state.summary); st.markdown("---")
        else: st.info("El resumen no fue generado. Activa la opción en el sidebar.");
        
        st.markdown("### 💭 Haz preguntas sobre el contenido")
        if st.session_state.qa_history:
            st.markdown("##### Historial de conversación")
            for i, qa in enumerate(st.session_state.qa_history):
                st.markdown(f"**Pregunta {i+1}:** {qa['question']}"); st.markdown(f"**Respuesta:** {qa['answer']}"); st.markdown("---")
        
        with st.form(key="question_form", clear_on_submit=True):
            user_question = st.text_area("Escribe tu pregunta aquí:", placeholder="Ej: ¿Qué dijo [persona] sobre [tema]?", height=100)
            submit_q, clear_h = st.columns(2)
            with submit_q: submit_question = st.form_submit_button("🚀 Enviar Pregunta", use_container_width=True)
            with clear_h: clear_history = st.form_submit_button("🗑️ Borrar Historial", use_container_width=True)

        if submit_question and user_question.strip():
            with st.spinner("🤔 Analizando..."):
                client = Groq(api_key=api_key); answer = answer_question(user_question, st.session_state.transcription, client, st.session_state.qa_history); st.session_state.qa_history.append({'question': user_question, 'answer': answer}); st.rerun()
        if clear_history: st.session_state.qa_history = []; st.rerun()

    if len(tabs) > 2:
        with tabs[2]:
            people_data = st.session_state.get('people'); brands_data = st.session_state.get('brands')
            if people_data:
                st.markdown("### 👤 Personas y Cargos");
                for name, data in people_data.items():
                    if "Error" in name: st.error(f"**{name}**: {data['details'].get('role', '')}"); continue
                    st.markdown(f"**{name}** - *{data['details'].get('role', 'No especificado')}*")
                    if data['mentions']:
                        with st.expander(f"Ver {len(data['mentions'])} mención(es)"):
                            for mention in data['mentions']:
                                col1, col2 = st.columns([0.2, 0.8]);
                                with col1: st.button(f"▶️ {mention['time']}", key=f"play_person_{name}_{mention['start']}", on_click=set_audio_time, args=(mention['start'],))
                                with col2: st.markdown(f"_{mention['context']}_")
                st.markdown("---")
            if brands_data:
                st.markdown("### 🏢 Marcas Mencionadas")
                for name, data in brands_data.items():
                    st.markdown(f"**{name}**")
                    if data['mentions']:
                        with st.expander(f"Ver {len(data['mentions'])} mención(es)"):
                            for mention in data['mentions']:
                                col1, col2 = st.columns([0.2, 0.8])
                                with col1: st.button(f"▶️ {mention['time']}", key=f"play_brand_{name}_{mention['start']}", on_click=set_audio_time, args=(mention['start'],))
                                with col2: st.markdown(f"_{mention['context']}_")
            if not people_data and not brands_data: st.info("No se identificaron entidades. Activa la opción en el sidebar o puede que no existan en el audio.")

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
        password_status = st.session_state.password_correct; st.session_state.clear(); st.session_state.password_correct = password_status; st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'><p><strong>Transcriptor Pro - Johnascriptor - v3.5.0 (Whisper-large-v3 | Llama-3.1)</strong></p><p style='font-size: 0.85rem;'>✨ Optimizado para noticias en español de Colombia</p></div>""", unsafe_allow_html=True)
