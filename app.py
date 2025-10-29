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
    password = st.session_state.get("password", "")
    correct_password = st.secrets.get("PASSWORD", "")
    if password and password == correct_password:
        st.session_state.password_correct = True
        st.session_state.password_attempted = False
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

    if st.session_state.get("password_attempted", False):
        st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    st.stop()


# --- INICIO DE LA APP PRINCIPAL ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- INICIALIZACIÓN DE ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []
if 'entity_search' not in st.session_state:
    st.session_state.entity_search = ""
if 'current_question' not in st.session_state:
    st.session_state.current_question = ""


# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

# --- FUNCIÓN CALLBACK PARA LIMPIAR BÚSQUEDA ---
def clear_search_callback():
    st.session_state.search_input = ""

def clear_entity_search_callback():
    st.session_state.entity_search = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
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
    components.html(f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button>
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
    </script>""", height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments: return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    for wrong, correct in {'Ã¡':'á','Ã©':'é','Ã­':'í','Ã³':'ó','Ãº':'ú','Ã±':'ñ','Ã\'':'Ñ','Â\u00bf':'¿','Â\u00a1':'¡'}.items():
        result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', lambda m: m.group(1) + m.group(2).upper(), result)
    if result and result[0].islower(): result = result[0].upper() + result[1:]
    return result.strip()

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---
@st.cache_data
def get_file_size_mb(file_bytes): return len(file_bytes) / (1024 * 1024)

@st.cache_data
def universal_audio_converter(file_bytes, filename, target_bitrate='96k'):
    original_size = get_file_size_mb(file_bytes)
    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext == '.mp3' and original_size < 8: return file_bytes, False, original_size, original_size
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_in:
        tmp_in.write(file_bytes)
        in_path = tmp_in.name
    out_path = in_path.rsplit('.', 1)[0] + '_converted.mp3'
    try:
        if file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']: clip = VideoFileClip(in_path).audio
        else: clip = AudioFileClip(in_path)
        clip.write_audiofile(out_path, codec='libmp3lame', bitrate=target_bitrate, fps=16000, nbytes=2, verbose=False, logger=None)
        clip.close()
        with open(out_path, 'rb') as f: mp3_bytes = f.read()
        final_size = get_file_size_mb(mp3_bytes)
        return mp3_bytes, True, original_size, final_size
    except Exception as e: return file_bytes, False, original_size, original_size
    finally:
        if os.path.exists(in_path): os.unlink(in_path)
        if os.path.exists(out_path): os.unlink(out_path)

def process_audio_for_transcription(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    original_size = get_file_size_mb(file_bytes)
    if MOVIEPY_AVAILABLE:
        p_bytes, converted, orig_mb, final_mb = universal_audio_converter(file_bytes, uploaded_file.name)
        if converted and final_mb < orig_mb:
            reduc = ((orig_mb - final_mb) / orig_mb * 100)
            msg = f"✅ Archivo optimizado: {orig_mb:.2f}MB → {final_mb:.2f}MB ({reduc:.1f}% menos)"
        elif converted: msg = f"✅ Convertido a MP3 optimizado: {final_mb:.2f}MB"
        else: msg = f"⚠️ No se pudo optimizar, usando original ({original_size:.2f}MB)."
        return p_bytes, msg
    return file_bytes, f"⚠️ MoviePy no disponible, usando original ({original_size:.2f}MB)."

# --- FUNCIONES DE ANÁLISIS CON IA ---
def post_process_with_llama(transcription_text, client):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un micro-servicio de corrección de texto. Tu única función es añadir tildes y completar terminaciones obvias (ej. `informaci` -> `información`) al texto en español. No añadas, elimines ni reescribas palabras. Devuelve solo el texto corregido."},
                {"role": "user", "content": f"Aplica tus reglas al siguiente texto:\n\n{transcription_text}"}],
            model="llama-3.1-8b-instant", temperature=0.0)
        return completion.choices[0].message.content.strip()
    except Exception: return transcription_text

def generate_summary(transcription_text, client):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Crea un resumen ejecutivo conciso (máximo 150 palabras) en un solo párrafo, manteniendo todas las tildes correctas en español."},
                {"role": "user", "content": f"Resume el siguiente texto:\n\n{transcription_text}"}],
            model="llama-3.1-8b-instant", temperature=0.3)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def answer_question(question, transcription_text, client, history):
    try:
        messages = [{"role": "system", "content": "Responde preguntas basándote únicamente en la transcripción. Si la respuesta no está, indícalo. Considera el historial de conversación."}]
        for qa in history:
            messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
        messages.append({"role": "user", "content": f"Transcripción:\n---\n{transcription_text}\n---\nPregunta: {question}"})
        completion = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant", temperature=0.2)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

def extract_entities_and_people(transcription_text, client):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": '''Identifica TODAS las entidades (personas, empresas, organizaciones).
REGLAS:
1. Extrae nombres completos de personas y entidades.
2. Clasifica cada una como: `Persona`, `Empresa`, `Organización`, `Institución`, `Marca` u `ONG`.
3. Proporciona el contexto (frase exacta donde se menciona).
FORMATO DE SALIDA (JSON VÁLIDO):
{ "entidades": [ { "name": "Nombre", "type": "Tipo", "context": "Contexto" } ] }
Si no hay entidades, devuelve: {"entidades": []}'''},
                {"role": "user", "content": f"Analiza esta transcripción:\n\n{transcription_text[:4000]}"}],
            model="llama-3.1-8b-instant", temperature=0.0, response_format={"type": "json_object"})
        data = json.loads(completion.choices[0].message.content)
        return data.get('entidades', [])
    except (json.JSONDecodeError, Exception): return []

def get_extended_context(segments, match_index, context_range=2):
    start = max(0, match_index - context_range)
    end = min(len(segments), match_index + context_range + 1)
    return [{'text': seg['text'].strip(), 'time': format_timestamp(seg['start']), 'start': seg['start'], 'is_match': (i == match_index)}
            for i, seg in enumerate(segments) if start <= i < end]

def export_to_srt(data):
    content = []
    for i, seg in enumerate(data.segments, 1):
        start = timedelta(seconds=seg['start']); end = timedelta(seconds=seg['end'])
        start_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        content.append(f"{i}\n{start_str} --> {end_str}\n{seg['text'].strip()}\n")
    return "\n".join(content)

def find_entity_in_segments(name, segments):
    matches = []
    pattern = re.compile(re.escape(name), re.IGNORECASE)
    for i, seg in enumerate(segments):
        if pattern.search(seg['text']): matches.append(i)
    return matches

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    language = st.selectbox("Idioma", ["es"])
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_llama_postprocess = st.checkbox("🤖 Post-procesamiento IA", True)
    enable_summary = st.checkbox("📝 Generar resumen", True)
    enable_entities = st.checkbox("👥 Extraer entidades/personas", True)
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    st.markdown("---")
    if MOVIEPY_AVAILABLE: st.success("✅ Optimización de audio activada.")
    else: st.warning("⚠️ MoviePy no disponible. `pip install moviepy`")
    st.info("💡 Soportados: MP3, MP4, WAV, M4A, MOV, etc.")
    st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
c1, c2 = st.columns([3, 1])
uploaded_file = c1.file_uploader("Selecciona un archivo", type=["mp3","mp4","wav","m4a","mpeg","mov","mkv"], label_visibility="collapsed")

if c2.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    keys_to_preserve = ['password_correct', 'password_attempted']
    for key in list(st.session_state.keys()):
        if key not in keys_to_preserve: del st.session_state[key]
    st.session_state.audio_start_time = 0; st.session_state.qa_history = []
    
    with st.spinner("🔄 Optimizando archivo..."):
        file_bytes, conv_msg = process_audio_for_transcription(uploaded_file)
        st.info(conv_msg)
        st.session_state.uploaded_audio_bytes = file_bytes

    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        tmp.write(file_bytes); tmp_path = tmp.name
    
    try:
        with st.spinner("🔄 Transcribiendo con IA..."):
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(uploaded_file.name, audio_file.read()), model=model_option,
                    language=language, response_format="verbose_json", temperature=0.0)
        
        text = fix_spanish_encoding(transcription.text)
        if enable_llama_postprocess:
            with st.spinner("🤖 Mejorando transcripción con IA..."):
                text = post_process_with_llama(text, client)
        
        for seg in transcription.segments: seg['text'] = fix_spanish_encoding(seg['text'])
        st.session_state.transcription = text
        st.session_state.transcription_data = transcription
        
        with st.spinner("🧠 Generando análisis..."):
            if enable_summary: st.session_state.summary = generate_summary(text, client)
            if enable_entities: st.session_state.entities = extract_entities_and_people(text, client)
        st.success("✅ ¡Análisis completado!"); st.balloons()
    except Exception as e: st.error(f"❌ Error: {e}")
    finally: os.unlink(tmp_path)
    st.rerun()


if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo"]
    if 'entities' in st.session_state and st.session_state.entities:
        tab_titles.append("👥 Entidades/Personas")
    tabs = st.tabs(tab_titles)
    
    # --- PESTAÑA DE TRANSCRIPCIÓN ---
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        MATCH_LINE_STYLE = "background-color:#1e3a5f;padding:0.8rem;border-radius:6px;border-left:4px solid #fca311;"
        CONTEXT_LINE_STYLE = "background-color:#1a1a1a;padding:0.6rem;border-radius:4px;color:#b8b8b8;"
        TRANSCRIPTION_BOX_STYLE = "background-color:#0E1117;color:#FAFAFA;border:1px solid #333;border-radius:10px;padding:1.5rem;max-height:500px;overflow-y:auto;font-family:'Source Code Pro',monospace;line-height:1.7;white-space:pre-wrap;font-size:0.95rem;"
        
        cs1, cs2 = st.columns([4, 1])
        search_query = cs1.text_input("🔎 Buscar en la transcripción:", key="search_input")
        if cs2.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True, disabled=not search_query): st.rerun()
        
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if not matches: st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matches)} coincidencia(s) encontrada(s).")
                    for i, match_idx in enumerate(matches, 1):
                        for ctx_seg in get_extended_context(segments, match_idx, context_lines):
                            ct, cc = st.columns([0.15, 0.85])
                            ct.button(f"▶️ {ctx_seg['time']}", key=f"play_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                            style = MATCH_LINE_STYLE if ctx_seg['is_match'] else CONTEXT_LINE_STYLE
                            text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx_seg['text']) if ctx_seg['is_match'] else ctx_seg['text']
                            cc.markdown(f"<div style='{style}'>{text}</div>", unsafe_allow_html=True)
                        if i < len(matches): st.markdown("---")
        
        st.markdown("📄 Transcripción completa:")
        html = st.session_state.transcription.replace('\n', '<br>')
        if search_query: html = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', html)
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{html}</div>', unsafe_allow_html=True)
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        c1.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", use_container_width=True)
        c3.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    # --- PESTAÑA DE RESUMEN Y PREGUNTAS ---
    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            st.markdown("---")
            st.markdown("### 💭 Haz preguntas sobre el contenido")
            
            # Lógica para manejar el envío de la pregunta al presionar Enter
            def handle_question_submit():
                user_q = st.session_state.current_question
                if user_q.strip():
                    with st.spinner("🤔 Analizando..."):
                        ans = answer_question(user_q, st.session_state.transcription, client, st.session_state.qa_history)
                        st.session_state.qa_history.insert(0, {'question': user_q, 'answer': ans})
                        st.session_state.current_question = "" # Limpiar input

            st.text_input(
                "Escribe tu pregunta y presiona Enter:",
                key="current_question",
                on_change=handle_question_submit,
                label_visibility="collapsed"
            )

            if st.session_state.qa_history:
                st.markdown("---")
                st.markdown("#### 📚 Historial de conversación")
                for qa in st.session_state.qa_history:
                    st.markdown(f"**P:** {qa['question']}")
                    st.markdown(f"**R:** {qa['answer']}")
                if st.button("🗑️ Borrar Historial", use_container_width=True):
                    st.session_state.qa_history = []
                    st.rerun()
        else:
            st.info("📝 El resumen no fue generado.")

    # --- PESTAÑA DE ENTIDADES Y PERSONAS ---
    if 'entities' in st.session_state and st.session_state.entities:
        with tabs[2]:
            st.markdown("### 👥 Entidades y Personas Identificadas")
            ces1, ces2 = st.columns([4, 1])
            entity_query = ces1.text_input("🔎 Buscar entidad específica:", key="entity_search")
            if ces2.button("🗑️ Limpiar", on_click=clear_entity_search_callback, use_container_width=True, key="b_clear_entity", disabled=not entity_query): st.rerun()

            entities_to_show = st.session_state.entities
            if entity_query:
                pattern = re.compile(re.escape(entity_query), re.IGNORECASE)
                entities_to_show = [e for e in entities_to_show if pattern.search(e.get('name', ''))]
                if entities_to_show: st.success(f"✅ {len(entities_to_show)} entidad(es) encontrada(s).")
                else: st.info("❌ No se encontraron entidades con ese nombre.")

            for entity in entities_to_show:
                name, type = entity.get('name', 'N/A'), entity.get('type', 'N/A')
                icon = "👤" if type == "Persona" else "🏢"
                st.markdown(f"**{icon} {name}** | **Tipo:** *{type}*")
                with st.expander("Ver contexto y menciones en audio"):
                    st.markdown(f"**Contexto IA:**\n> {entity.get('context', 'N/A')}")
                    matches = find_entity_in_segments(name, st.session_state.transcription_data.segments)
                    if matches:
                        st.markdown(f"**📍 {len(matches)} mención(es) en la transcripción:**")
                        for match_idx in matches:
                            st.markdown("---")
                            for ctx_seg in get_extended_context(st.session_state.transcription_data.segments, match_idx, context_lines):
                                col_t, col_c = st.columns([0.15, 0.85])
                                col_t.button(f"▶️ {ctx_seg['time']}", key=f"ent_play_{name}_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],), use_container_width=True)
                                style = MATCH_LINE_STYLE if ctx_seg['is_match'] else CONTEXT_LINE_STYLE
                                text_html = re.sub(re.escape(name), f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx_seg['text'], flags=re.IGNORECASE) if ctx_seg['is_match'] else ctx_seg['text']
                                col_c.markdown(f"<div style='{style}'>{text_html}</div>", unsafe_allow_html=True)
                    else: st.info("ℹ️ No se encontraron menciones exactas en los segmentos.")

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
    <p><strong>Transcriptor Pro - Johnascriptor - v3.8.0</strong></p>
    <p style='font-size: 0.9rem;'>🎙️ whisper-large-v3 | 🤖 llama-3.1-8b-instant | 🎵 Optimización MP3 96kbps</p>
    <p style='font-size: 0.85rem;'>✨ Con pestaña unificada de entidades y envío de preguntas con Enter</p>
    <p style='font-size: 0.8rem; margin-top: 0.5rem;'>Desarrollado por Johnathan Cortés</p>
</div>
""", unsafe_allow_html=True)
