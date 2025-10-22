import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter
import io

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
if 'audio_player_key' not in st.session_state:
    st.session_state.audio_player_key = "audio_player_0"

# --- FUNCIÓN PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = start_seconds
    current_key_index = int(st.session_state.audio_player_key.split("_")[-1])
    st.session_state.audio_player_key = f"audio_player_{current_key_index + 1}"

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1', r'\bqu\s+se\b': 'qué se', r'\bqu\s+es\b': 'qué es',
    r'\bqu\s+fue\b': 'qué fue', r'\bqu\s+hay\b': 'qué hay', r'\bqu\s+significa\b': 'qué significa',
    r'\bqu\s+pasa\b': 'qué pasa', r'\bPor\s+qu(?!\s+[eé])\b': 'Por qué', r'\bpor\s+qu(?!\s+[eé])\b': 'por qué',
    r'\bfundaci(?=\s|$)': 'fundación', 'Fundaci(?=\s|$)': 'Fundación', r'\binformaci(?=\s|$)': 'información',
    'Informaci(?=\s|$)': 'Información', r'\bsituaci(?=\s|$)': 'situación', 'Situaci(?=\s|$)': 'Situación',
    r'\bdeclaraci(?=\s|$)': 'declaración', 'Declaraci(?=\s|$)': 'Declaración', r'\bnaci(?=\s|$)': 'nación',
    'Naci(?=\s|$)': 'Nación', r'\bpoblaci(?=\s|$)': 'población', 'Poblaci(?=\s|$)': 'Población',
    r'\breuni(?=\s|$)': 'reunión', 'Reuni(?=\s|$)': 'Reunión', r'\bopini(?=\s|$)': 'opinión',
    'Opini(?=\s|$)': 'Opinión', r'\bresoluci(?=\s|$)': 'resolución', 'Resoluci(?=\s|$)': 'Resolución',
    r'\borganizaci(?=\s|$)': 'organización', 'Organizaci(?=\s|$)': 'Organización', r'\bprotecci(?=\s|$)': 'protección',
    'Protecci(?=\s|$)': 'Protección', r'\bparticipaci(?=\s|$)': 'participación', 'Participaci(?=\s|$)': 'Participación',
    r'\binvestigaci(?=\s|$)': 'investigación', 'Investigaci(?=\s|$)': 'Investigación', r'\beducaci(?=\s|$)': 'educación',
    'Educaci(?=\s|$)': 'Educación', r'\bsanci(?=\s|$)': 'sanción', 'Sanci(?=\s|$)': 'Sanción',
    r'\bcomunicaci(?=\s|$)': 'comunicación', 'Comunicaci(?=\s|$)': 'Comunicación', r'\boperaci(?=\s|$)': 'operación',
    'Operaci(?=\s|$)': 'Operación', r'\brelaci(?=\s|$)': 'relación', 'Relaci(?=\s|$)': 'Relación',
    r'\badministraci(?=\s|$)': 'administración', 'Administraci(?=\s|$)': 'Administración',
    r'\bimplementaci(?=\s|$)': 'implementación', 'Implementaci(?=\s|$)': 'Implementación',
    r'\bpoli(?=\s|$)': 'política', 'Poli(?=\s|$)': 'Política', r'\bcompa(?=\s|$)': 'compañía',
    'Compa(?=\s|$)': 'Compañía', r'\beconom(?=\s|$)': 'economía', 'Econom(?=\s|$)': 'Economía',
    r'\benergi(?=\s|$)': 'energía', 'Energi(?=\s|$)': 'Energía', r'\bgeograf(?=\s|$)': 'geografía',
    'Geograf(?=\s|$)': 'Geografía', r'\bpai(?=\s|$)': 'país', 'Pai(?=\s|$)': 'País', r'\bda(?=\s|$)': 'día',
    'Da(?=\s|$)': 'Día', r'\bmiérco(?=\s|$)': 'miércoles', 'Miérco(?=\s|$)': 'Miércoles',
    r'\bdocument(?=\s|$)': 'documental', 'Document(?=\s|$)': 'Documental', r'\bsostenib(?=\s|$)': 'sostenible',
    'Sostenib(?=\s|$)': 'Sostenible', r'\bEntretenim(?=\s|$)': 'Entretenimiento', 'entretenim(?=\s|$)': 'entretenimiento',
}

# --- FUNCIONES AUXILIARES ---

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    components.html(f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button>
    <script>
    document.getElementById("{button_id}").onclick = function() {{
        const ta = document.createElement("textarea");
        ta.value = {text_json};
        ta.style.position="fixed"; ta.style.top="-9999px"; ta.style.left="-9999px";
        document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
        const btn = document.getElementById("{button_id}"); const original = btn.innerText;
        btn.innerText = "✅ ¡Copiado!";
        setTimeout(() => {{ btn.innerText = original; }}, 2000);
    }};
    </script>""", height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02}:{m:02}:{s:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments: return "No se encontraron segmentos."
    return "\n".join([f"[{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}] {s['text'].strip()}" for s in data.segments])

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    fixes = {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for w, c in fixes.items(): result = result.replace(w, c)
    for p, r in SPANISH_WORD_CORRECTIONS.items(): result = re.sub(p, r, result)
    result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result, flags=re.IGNORECASE)
    result = re.sub(r'(?<=\.\s)([a-z])', lambda m: m.group(1).upper(), result)
    return result.strip()

def check_transcription_quality(text):
    if not text: return []
    issues = []
    if any(c in text for c in ['Ã', 'Â']): issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática.")
    if re.search(r'\b(qu|sostenib|fundaci|informaci)\s', text, re.IGNORECASE): issues.append("ℹ️ Se aplicaron correcciones de tildes y palabras cortadas.")
    return issues

# --- CONVERSIÓN Y COMPRESIÓN DE AUDIO ---

def convert_video_to_audio(video_bytes, video_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp:
            tmp.write(video_bytes)
            video_path = tmp.name
        audio_path = f"{video_path}.mp3"
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None)
        video.close()
        with open(audio_path, 'rb') as f: audio_bytes = f.read()
        os.unlink(video_path); os.unlink(audio_path)
        return audio_bytes, True
    except Exception: return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp:
            tmp.write(audio_bytes)
            audio_path = tmp.name
        compressed_path = f"{audio_path}_comp.mp3"
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(compressed_path, codec='mp3', bitrate='96k', verbose=False, logger=None)
        audio.close()
        with open(compressed_path, 'rb') as f: compressed_bytes = f.read()
        os.unlink(audio_path); os.unlink(compressed_path)
        return compressed_bytes
    except Exception: return audio_bytes

def get_file_size_mb(file_bytes): return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS IA ---

def generate_summary(text, client):
    try:
        completion = client.chat.completions.create(model="llama-3.1-70b-versatile", temperature=0.3, max_tokens=500, messages=[{"role": "system", "content": "Crea resúmenes profesionales y concisos en un solo párrafo. Mantén todas las tildes correctas en español."}, {"role": "user", "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) del siguiente texto. Ve directo al contenido:\n\n{text}"}])
        return completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def answer_question(question, text, client, history):
    try:
        messages = [{"role": "system", "content": "Eres un asistente experto. Responde preguntas sobre la transcripción de forma precisa y concisa. Basa tus respuestas ÚNICAMENTE en la transcripción. Si la información no está, indícalo. Mantén las tildes correctas."}]
        for qa in history: messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
        messages.append({"role": "user", "content": f"Transcripción:\n---\n{text}\n---\nPregunta: {question}"})
        completion = client.chat.completions.create(model="llama-3.1-70b-versatile", temperature=0.2, max_tokens=800, messages=messages)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

def extract_quotes(segments):
    quotes = []
    keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró']
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        if ('"' in text or '«' in text or '»' in text) or any(k in text.lower() for k in keywords):
            context = f"{segments[i-1]['text'].strip() if i > 0 else ''} {text} {segments[i+1]['text'].strip() if i < len(segments) - 1 else ''}".strip()
            quotes.append({'time': format_timestamp(seg['start']), 'text': text, 'full_context': context, 'start': seg['start'], 'type': 'quote' if '"' in text else 'declaration'})
    return sorted(quotes, key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)[:10]

def extract_people_and_roles(text, client):
    try:
        completion = client.chat.completions.create(model="llama-3.1-70b-versatile", temperature=0.1, max_tokens=1024, response_format={"type": "json_object"}, messages=[{"role": "system", "content": 'Analiza la transcripción. Identifica personas y sus roles. Devuelve una lista JSON de objetos con claves "name", "role" y "context". Si no hay rol, usa "No especificado".'}, {"role": "user", "content": f"Analiza: {text}"}])
        data = json.loads(completion.choices[0].message.content)
        return next((v for v in data.values() if isinstance(v, list)), [])
    except (json.JSONDecodeError, Exception) as e: return [{"name": "Error de Análisis", "role": str(e), "context": "No se pudo procesar la respuesta de la IA."}]

def get_extended_context(segments, idx, context_range=2):
    start = max(0, idx - context_range)
    end = min(len(segments), idx + context_range + 1)
    
    context_list = []
    for i in range(start, end):
        seg = segments[i]
        context_list.append({
            'text': seg['text'].strip(), 
            'time': format_timestamp(seg['start']), 
            'start': seg['start'], 
            'is_match': i == idx
        })
    return context_list

def export_to_srt(data):
    content = []
    for i, seg in enumerate(data.segments, 1):
        start_td, end_td = timedelta(seconds=seg['start']), timedelta(seconds=seg['end'])
        start = f"{start_td.seconds//3600:02}:{(start_td.seconds//60)%60:02}:{start_td.seconds%60:02},{start_td.microseconds//1000:03}"
        end = f"{end_td.seconds//3600:02}:{(end_td.seconds//60)%60:02}:{end_td.seconds%60:02},{end_td.microseconds//1000:03}"
        content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(content)

# --- INTERFAZ DE LA APP ---

st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    language = st.selectbox("Idioma", ["es"])
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1)
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_tilde_fix = st.checkbox("✨ Corregir tildes", value=True)
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas", value=True)
    enable_people = st.checkbox("👤 Extraer personas", value=True)

    st.markdown("---")
    st.subheader("🔍 Búsqueda")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    
    st.markdown("---")
    st.subheader("🔧 Audio")
    if MOVIEPY_AVAILABLE:
        st.info("MP4 > 25 MB se convertirán a audio.")
        compress_audio_option = st.checkbox("📦 Comprimir audio", value=False)
    else:
        st.warning("MoviePy no disponible.")
        compress_audio_option = False
    
    st.markdown("---")
    st.info("Formatos: MP3, MP4, WAV, etc.")
    st.success("API Key configurada")

st.subheader("📤 Sube tu archivo")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Transcribir", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.audio_start_time = 0
        st.session_state.audio_player_key = "audio_player_0"
        st.session_state.last_search = ""
        st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
        st.session_state.qa_history = []
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                if os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4', '.mpeg', '.webm'] and MOVIEPY_AVAILABLE and get_file_size_mb(file_bytes) > 25:
                    with st.spinner("🎬 Convirtiendo video a audio..."):
                        file_bytes, _ = convert_video_to_audio(file_bytes, uploaded_file.name)
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo audio..."):
                        file_bytes = compress_audio(file_bytes, uploaded_file.name)
                st.session_state.uploaded_audio_bytes = file_bytes
                
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA..."):
                    with open(tmp_path, "rb") as audio_file:
                        prompt = "Transcribe en español, prestando atención a acentos y palabras completas: qué, por qué, sí, fundación, información, situación, etc."
                        transcription = client.audio.transcriptions.create(file=(uploaded_file.name, audio_file.read()), model=model_option, temperature=temperature, language=language, response_format="verbose_json", prompt=prompt if language == "es" else None)
                os.unlink(tmp_path)
                
                text = transcription.text
                if enable_tilde_fix and language == "es":
                    with st.spinner("✨ Aplicando correcciones..."):
                        text = fix_spanish_encoding(text)
                        for seg in transcription.segments:
                            seg['text'] = fix_spanish_encoding(seg['text'])
                        for issue in check_transcription_quality(text):
                            st.info(issue)
                
                st.session_state.transcription = text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis..."):
                    if enable_summary: st.session_state.summary = generate_summary(text, client)
                    if enable_quotes: st.session_state.quotes = extract_quotes(transcription.segments)
                    if enable_people: st.session_state.people = extract_people_and_roles(text, client)
                
                st.success("✅ ¡Análisis completado!")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Error: {e}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza")
    
    st.audio(io.BytesIO(st.session_state.uploaded_audio_bytes), 
             start_time=st.session_state.audio_start_time,
             key=st.session_state.audio_player_key)
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo", "💬 Citas"]
    if 'people' in st.session_state:
        tab_titles.append("👥 Personas")
    
    tabs = st.tabs(tab_titles)
    
    with tabs[0]:
        st.markdown(f"""
        <style>
            .match-line {{ background-color: #fff3cd; color: #533f00; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #ffc107; font-size: 1rem; line-height: 1.6; margin-bottom: 4px; }}
            .context-line {{ background-color: #f0f2f6; color: #31333F; padding: 0.6rem; border-radius: 4px; border-left: 2px solid #dcdcdc; font-size: 0.92rem; line-height: 1.5; margin-bottom: 2px; }}
            [data-theme="dark"] .match-line {{ background-color: #1e3a5f !important; color: #ffffff !important; border-left: 4px solid #fca311 !important; }}
            [data-theme="dark"] .context-line {{ background-color: #262730 !important; color: #b8b8b8 !important; border-left: 2px solid #404040 !important; }}
        </style>""", unsafe_allow_html=True)

        col_s1, col_s2 = st.columns([4, 1])
        with col_s1:
            search_query = st.text_input("🔎 Buscar:", value=st.session_state.get('last_search', ''), key=f"search_input_{st.session_state.get('search_counter', 0)}")
            st.session_state.last_search = search_query
        with col_s2:
            st.write("")
            # Línea corregida con indentación estándar
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query):
                st.session_state.last_search = ""
                st.session_state.search_counter += 1
                st.rerun()
        
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, s in enumerate(segments) if pattern.search(s['text'])]
                
                if not matches:
                    st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matches)} coincidencia(s) encontrada(s)")
                    for i, match_idx in enumerate(matches, 1):
                        st.markdown(f"### 🎯 Resultado {i}")
                        ctx_segments = get_extended_context(segments, match_idx, context_lines)
                        for seg in ctx_segments:
                            col_t, col_c = st.columns([0.15, 0.85])
                            with col_t:
                                if st.button(f"▶️ {seg['time']}", key=f"play_ctx_{i}_{seg['start']}", use_container_width=True):
                                    set_audio_time(int(seg['start']))
                                    st.rerun()
                            with col_c:
                                highlight_html = f'<span style="background-color:#fca311;color:#14213d;padding:2px 4px;border-radius:4px;">\\g<0></span>'
                                if seg['is_match']:
                                    highlighted_text = pattern.sub(highlight_html, seg['text'])
                                    st.markdown(f"<div class='match-line'><strong>🎯 </strong>{highlighted_text}</div>", unsafe_allow_html=True)
                                else:
                                    st.markdown(f"<div class='context-line'>{seg['text']}</div>", unsafe_allow_html=True)
                        if i < len(matches):
                            st.markdown("---")
        
        st.markdown("**📄 Transcripción completa:**")
        html = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            highlight_html = f'<span style="background-color:#fca311;color:#14213d;padding:2px 4px;border-radius:4px;">\\g<0></span>'
            html = re.compile(re.escape(search_query), re.IGNORECASE).sub(highlight_html, html)
        st.markdown(f"<div style='background-color:#0E1117;color:#FAFAFA;border:1px solid #333;border-radius:10px;padding:1.5rem;max-height:500px;overflow-y:auto;font-family:monospace;line-height:1.7;'>{html}</div>", unsafe_allow_html=True)
        st.write("")
        
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        with c1: st.download_button("💾 TXT Simple", st.session_state.transcription.encode('utf-8'), "transcripcion.txt", use_container_width=True)
        with c2: st.download_button("💾 TXT+Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data).encode('utf-8'), "transcripcion_tiempos.txt", use_container_width=True)
        with c3: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data).encode('utf-8'), "subtitulos.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            st.write("")
            cs1, cs2 = st.columns([3, 1])
            with cs1: st.download_button("💾 Descargar", st.session_state.summary.encode('utf-8'), "resumen.txt", use_container_width=True)
            with cs2: create_copy_button(st.session_state.summary)
            
            st.markdown("---")
            st.markdown("### 💭 Haz preguntas")
            if 'qa_history' not in st.session_state: st.session_state.qa_history = []
            
            if st.session_state.qa_history:
                st.markdown("#### 📚 Historial")
                for i, qa in enumerate(st.session_state.qa_history):
                    st.markdown(f"**🙋 P{i+1}:** {qa['question']}\n\n**🤖 R:** {qa['answer']}\n\n---")
            
            with st.form("q_form", clear_on_submit=True):
                q = st.text_area("Escribe tu pregunta:", height=100)
                cq1, cq2, _ = st.columns([2, 2, 1])
                with cq1: submit_q = st.form_submit_button("🚀 Enviar", use_container_width=True)
                with cq2: clear_h = st.form_submit_button("🗑️ Borrar Historial", use_container_width=True)
            
            if submit_q and q.strip():
                with st.spinner("🤔 Analizando..."):
                    client = Groq(api_key=api_key)
                    answer = answer_question(q, st.session_state.transcription, client, st.session_state.qa_history)
                    st.session_state.qa_history.append({'question': q, 'answer': answer})
                    st.rerun()
            if clear_h:
                st.session_state.qa_history = []
                st.rerun()
        else:
            st.info("📝 Resumen no generado. Actívalo y vuelve a transcribir.")

    with tabs[2]:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones")
            st.caption(f"{len(st.session_state.quotes)} citas/declaraciones encontradas.")
            for i, q in enumerate(st.session_state.quotes):
                st.markdown("🗣️ **Cita Textual**" if q['type'] == 'quote' else "📢 **Declaración**")
                c_q1, c_q2 = st.columns([0.12, 0.88])
                with c_q1:
                    if st.button(f"▶️ {q['time']}", key=f"q_{i}"):
                        set_audio_time(int(q['start']))
                        st.rerun()
                with c_q2:
                    st.markdown(f"*{q['text']}*")
                    if q['full_context'] != q['text']:
                        with st.expander("📄 Ver contexto"):
                            st.markdown(q['full_context'])
                st.markdown("---")
        else:
            st.info("💬 No se identificaron citas relevantes.")

    if 'people' in st.session_state:
        with tabs[3]:
            st.markdown("### 👥 Personas y Cargos")
            people = st.session_state.people
            if people and "Error" not in people[0]['name']:
                st.caption(f"{len(people)} personas clave identificadas.")
                for p in people:
                    st.markdown(f"**👤 {p['name']}**\n\n&nbsp;&nbsp;&nbsp;&nbsp;*Rol:* {p.get('role', 'No especificado')}")
                    with st.expander("📝 Ver contexto"):
                        st.markdown(f"> {p.get('context', 'N/A')}")
            elif people:
                st.error(f"**{people[0]['name']}**: {people[0]['role']}")
                st.info(f"Contexto: {people[0]['context']}")
            else:
                st.info("👤 No se identificaron personas específicas.")

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
        keys_to_clear = ["transcription", "transcription_data", "uploaded_audio_bytes", "audio_start_time", "summary", "quotes", "last_search", "search_counter", "people", "qa_history", "audio_player_key"]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

st.markdown("---")
st.markdown("<div style='text-align:center;color:#666;'><p><strong>Transcriptor Pro - v2.4.4</strong> - por Johnathan Cortés 🤖</p></div>", unsafe_allow_html=True)
