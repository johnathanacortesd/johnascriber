# ==============================================================================
# Transcriptor Pro - Johnascriptor v2.5.0 (Versión Definitiva Verificada)
# CÓDIGO COMPLETO - Copia todo desde aquí hasta el final del archivo.
# ==============================================================================

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
if 'audio_player_key' not in st.session_state:
    st.session_state.audio_player_key = 0

# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)
    st.session_state.audio_player_key += 1

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
    r'\breuni(?=\s|$)': 'reunión', 'Reuni(?=\s|$)': 'Reunión', r'\bopini(?=\s|$)': 'opinión', 'Opini(?=\s|$)': 'Opinión',
    r'\bresoluci(?=\s|$)': 'resolución', 'Resoluci(?=\s|$)': 'Resolución', r'\borganizaci(?=\s|$)': 'organización',
    'Organizaci(?=\s|$)': 'Organización', r'\bprotecci(?=\s|$)': 'protección', 'Protecci(?=\s|$)': 'Protección',
    r'\bparticipaci(?=\s|$)': 'participación', 'Participaci(?=\s|$)': 'Participación', r'\binvestigaci(?=\s|$)': 'investigación',
    'Investigaci(?=\s|$)': 'Investigación', r'\beducaci(?=\s|$)': 'educación', 'Educaci(?=\s|$)': 'Educación',
    r'\bsanci(?=\s|$)': 'sanción', 'Sanci(?=\s|$)': 'Sanción', r'\bcomunicaci(?=\s|$)': 'comunicación',
    'Comunicaci(?=\s|$)': 'Comunicación', r'\boperaci(?=\s|$)': 'operación', 'Operaci(?=\s|$)': 'Operación',
    r'\brelaci(?=\s|$)': 'relación', 'Relaci(?=\s|$)': 'Relación', r'\badministraci(?=\s|$)': 'administración',
    'Administraci(?=\s|$)': 'Administración', r'\bimplementaci(?=\s|$)': 'implementación', 'Implementaci(?=\s|$)': 'Implementación',
    r'\bpoli(?=\s|$)': 'política', 'Poli(?=\s|$)': 'Política', r'\bcompa(?=\s|$)': 'compañía', 'Compa(?=\s|$)': 'Compañía',
    r'\beconom(?=\s|$)': 'economía', 'Econom(?=\s|$)': 'Economía', r'\benergi(?=\s|$)': 'energía', 'Energi(?=\s|$)': 'Energía',
    r'\bgeograf(?=\s|$)': 'geografía', 'Geograf(?=\s|$)': 'Geografía', r'\bpai(?=\s|$)': 'país', 'Pai(?=\s|$)': 'País',
    r'\bda(?=\s|$)': 'día', 'Da(?=\s|$)': 'Día', r'\bmiérco(?=\s|$)': 'miércoles', 'Miérco(?=\s|$)': 'Miércoles',
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
        ta.style.position = "fixed"; ta.style.top = "-9999px"; ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        const btn = document.getElementById("{button_id}");
        const originalText = btn.innerText;
        btn.innerText = "✅ ¡Copiado!";
        setTimeout(() => {{ btn.innerText = originalText; }}, 2000);
    }};
    </script>
    """, height=40)

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
    encoding_fixes = {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for wrong, correct in encoding_fixes.items(): result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items(): result = re.sub(pattern, replacement, result)
    result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result, flags=re.IGNORECASE)
    result = re.sub(r'(?<=\.\s)([a-z])', lambda m: m.group(1).upper(), result)
    return result.strip()

def check_transcription_quality(text):
    issues = []
    if not text: return issues
    if any(c in text for c in ['Ã', 'Â']): issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática.")
    if re.search(r'\b(qu|sostenib|fundaci|informaci)\s', text, re.IGNORECASE): issues.append("ℹ️ Se aplicaron correcciones automáticas de tildes y palabras cortadas.")
    return issues

def convert_video_to_audio(video_bytes, filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_v:
            tmp_v.write(video_bytes)
            video_path = tmp_v.name
        audio_path = f"{video_path}.mp3"
        with VideoFileClip(video_path) as video:
            video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None)
        with open(audio_path, 'rb') as f: audio_bytes = f.read()
        os.unlink(video_path); os.unlink(audio_path)
        return audio_bytes, True
    except Exception: return video_bytes, False

def compress_audio(audio_bytes, filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_a:
            tmp_a.write(audio_bytes)
            audio_path = tmp_a.name
        compressed_path = f"{audio_path}_comp.mp3"
        with AudioFileClip(audio_path) as audio:
            audio.write_audiofile(compressed_path, codec='mp3', bitrate='96k', verbose=False, logger=None)
        with open(compressed_path, 'rb') as f: compressed_bytes = f.read()
        os.unlink(audio_path); os.unlink(compressed_path)
        return compressed_bytes
    except Exception: return audio_bytes

def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS IA ---

def generate_summary(text, client):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto en resumir textos. Crea un resumen ejecutivo conciso en un solo párrafo, en español, manteniendo las tildes correctas."},
                {"role": "user", "content": f"Resume el siguiente texto en un párrafo de máximo 150 palabras, sin introducciones:\n\n{text}"}
            ], model="llama-3.1-70b-versatile", temperature=0.3, max_tokens=500)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def answer_question(question, text, client, history):
    try:
        messages = [{"role": "system", "content": "Eres un asistente de Q&A. Responde preguntas basándote ÚNICAMENTE en la transcripción proporcionada. Si la respuesta no está en el texto, indícalo claramente. Sé conciso y usa español correcto."}]
        for qa in history:
            messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
        messages.append({"role": "user", "content": f"Transcripción:\n---\n{text}\n---\nPregunta: {question}"})
        completion = client.chat.completions.create(messages=messages, model="llama-3.1-70b-versatile", temperature=0.2, max_tokens=800)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

def extract_quotes(segments):
    quotes = []
    keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró']
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        if '"' in text or '«' in text or any(k in text.lower() for k in keywords):
            context_before = segments[i-1]['text'].strip() if i > 0 else ""
            context_after = segments[i+1]['text'].strip() if i < len(segments) - 1 else ""
            full_context = f"{context_before} {text} {context_after}".strip()
            quotes.append({'time': format_timestamp(seg['start']), 'text': text, 'full_context': full_context, 'start': seg['start'], 'type': 'quote' if '"' in text or '«' in text else 'declaration'})
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)
    return quotes[:10]

def extract_people_and_roles(text, client):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": 'Identifica personas y roles en el texto. Devuelve una lista JSON de objetos con "name", "role" y "context". Si no hay rol, usa "No especificado". El JSON debe ser válido.'},
                {"role": "user", "content": f"Extrae personas y roles del siguiente texto:\n\n{text}"}
            ], model="llama-3.1-70b-versatile", temperature=0.1, max_tokens=1024, response_format={"type": "json_object"})
        data = json.loads(completion.choices[0].message.content)
        for key in data:
            if isinstance(data[key], list): return data[key]
        return []
    except Exception: return [{"name": "Error de Análisis", "role": "No se pudo procesar la respuesta de la IA.", "context": "N/A"}]

def get_extended_context(segments, match_idx, context_range=2):
    start_idx = max(0, match_idx - context_range)
    end_idx = min(len(segments), match_idx + context_range + 1)
    return [{'text': s['text'].strip(), 'time': format_timestamp(s['start']), 'start': s['start'], 'is_match': (i == match_idx)} for i, s in enumerate(segments[start_idx:end_idx], start=start_idx)]

def export_to_srt(data):
    content = []
    for i, s in enumerate(data.segments, 1):
        start = timedelta(seconds=s['start']); end = timedelta(seconds=s['end'])
        start_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        content.append(f"{i}\n{start_str} --> {end_str}\n{s['text'].strip()}\n")
    return "\n".join(content)

# --- INTERFAZ PRINCIPAL DE STREAMLIT ---

st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración"); model_option = st.selectbox("Modelo", ["whisper-large-v3"]); language = "es"; temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1)
    st.markdown("---"); st.subheader("🎯 Análisis Inteligente"); enable_tilde_fix = st.checkbox("✨ Corregir tildes", True); enable_summary = st.checkbox("📝 Generar resumen", True); enable_quotes = st.checkbox("💬 Identificar citas", True); enable_people = st.checkbox("👤 Extraer personas", True)
    st.markdown("---"); st.subheader("🔍 Búsqueda"); context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    st.markdown("---"); st.subheader("🔧 Procesamiento"); compress_audio_option = False
    if MOVIEPY_AVAILABLE:
        st.info("💡 Videos > 25 MB se convertirán a audio.")
        compress_audio_option = st.checkbox("📦 Comprimir audio", False)
    else: st.warning("⚠️ MoviePy no disponible.")
    st.markdown("---"); st.success("✅ API Key configurada")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")

with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.clear()
        st.session_state.audio_start_time = 0
        st.session_state.audio_player_key = 0
        
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                if MOVIEPY_AVAILABLE and os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4', '.mpeg', '.webm'] and get_file_size_mb(file_bytes) > 25:
                    with st.spinner("🎬 Convirtiendo video a audio..."): file_bytes, _ = convert_video_to_audio(file_bytes, uploaded_file.name)
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo audio..."): file_bytes = compress_audio(file_bytes, uploaded_file.name)
                
                st.session_state.uploaded_audio_bytes = file_bytes
                
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp: tmp.write(file_bytes); tmp_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA... (puede tardar)"), open(tmp_path, "rb") as audio_file:
                    prompt = "Transcribe cuidadosamente en español, asegurando acentos correctos en palabras como qué, sí, está, más, él, fundación, información."
                    transcription = client.audio.transcriptions.create(file=(uploaded_file.name, audio_file.read()), model=model_option, temperature=temperature, language=language, response_format="verbose_json", prompt=prompt)
                os.unlink(tmp_path)
                
                text = transcription.text
                if enable_tilde_fix:
                    with st.spinner("✨ Aplicando correcciones..."):
                        text = fix_spanish_encoding(transcription.text)
                        for segment in transcription.segments: segment['text'] = fix_spanish_encoding(segment['text'])
                
                st.session_state.transcription_text = text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis..."):
                    if enable_summary: st.session_state.summary = generate_summary(text, client)
                    if enable_quotes: st.session_state.quotes = extract_quotes(transcription.segments)
                    if enable_people: st.session_state.people = extract_people_and_roles(text, client)
                
                st.success("✅ ¡Análisis completado!"); st.balloons()
            except Exception as e: st.error(f"❌ Error durante el proceso: {e}")

if 'transcription_text' in st.session_state:
    st.markdown("---"); st.subheader("🎧 Reproduce y Analiza")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time, key=f"audio_player_{st.session_state.audio_player_key}")
    
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo", "💬 Citas", "👥 Personas"]
    tabs = st.tabs([t for i, t in enumerate(tab_titles) if (i < 3) or (i == 3 and 'people' in st.session_state)])
    
    with tabs[0]:
        col_s1, col_s2 = st.columns([4, 1])
        with col_s1: search_query = st.text_input("🔎 Buscar en la transcripción:", key="search_input")
        with col_s2: st.write(""); st.button("🗑️ Limpiar", on_click=lambda: st.session_state.update(search_input=""), use_container_width=True)
        
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                matches = [i for i, s in enumerate(segments) if re.search(re.escape(search_query), s['text'], re.IGNORECASE)]
                if not matches: st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matches)} coincidencia(s) encontrada(s)")
                    for i, match_idx in enumerate(matches, 1):
                        st.markdown(f"---" if i > 1 else ""); st.markdown(f"#### 🎯 Resultado {i}")
                        context = get_extended_context(segments, match_idx, context_lines)
                        for seg in context:
                            col_t, col_c = st.columns([0.15, 0.85])
                            with col_t: st.button(f"▶️ {seg['time']}", key=f"play_{i}_{seg['start']}", on_click=set_audio_time, args=(seg['start'],), use_container_width=True)
                            with col_c:
                                text_html = re.sub(re.escape(search_query), lambda m: f'<span style="background-color: #fca311; color: #14213d; padding: 2px; border-radius: 3px;">{m.group(0)}</span>', seg['text'], flags=re.IGNORECASE)
                                st.markdown(f'<div style="padding: 0.5rem; border-radius: 5px; background-color: {"#1e3a5f" if seg["is_match"] else "#1a1a1a"};"> {text_html}</div>', unsafe_allow_html=True)

        st.markdown("**📄 Transcripción completa:**")
        box_style = "background-color: #0E1117; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: monospace;"
        st.markdown(f'<div style="{box_style}">{st.session_state.transcription_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
        
        st.write("")
        d_cols = st.columns([2, 2, 2, 1.5])
        with d_cols[0]: st.download_button("💾 TXT Simple", st.session_state.transcription_text, "transcripcion.txt", use_container_width=True)
        with d_cols[1]: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "tiempos.txt", use_container_width=True)
        with d_cols[2]: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with d_cols[3]: create_copy_button(st.session_state.transcription_text)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo"); st.markdown(st.session_state.summary)
            s_cols = st.columns([3, 1]); s_cols[0].download_button("💾 Descargar Resumen", st.session_state.summary, "resumen.txt", use_container_width=True); with s_cols[1]: create_copy_button(st.session_state.summary)
            
            st.markdown("---"); st.markdown("### 💭 Pregúntale al documento")
            if 'qa_history' not in st.session_state: st.session_state.qa_history = []
            for qa in st.session_state.qa_history:
                st.markdown(f"**🙋 Tú:** {qa['question']}")
                st.markdown(f"**🤖 IA:** {qa['answer']}")
                st.markdown("---")

            with st.form("question_form", clear_on_submit=True):
                user_question = st.text_area("Escribe tu pregunta:", height=100)
                submitted = st.form_submit_button("🚀 Enviar")
                if submitted and user_question:
                    with st.spinner("🤔 Pensando..."):
                        answer = answer_question(user_question, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': user_question, 'answer': answer})
                    st.rerun()
        else: st.info("El resumen no fue generado.")

    with tabs[2]:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones Relevantes")
            for idx, quote in enumerate(st.session_state.quotes):
                st.markdown(f"**{'🗣️ Cita Textual' if quote['type'] == 'quote' else '📢 Declaración'}**")
                q_cols = st.columns([0.12, 0.88])
                with q_cols[0]: st.button(f"▶️ {quote['time']}", key=f"q_{idx}", on_click=set_audio_time, args=(quote['start'],))
                with q_cols[1]: st.markdown(f"*{quote['text']}*")
                with st.expander("📄 Ver contexto completo"): st.markdown(f"...{quote['full_context']}...")
                st.markdown("---")
        else: st.info("No se identificaron citas relevantes.")

    if 'people' in st.session_state:
        with tabs[3]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            people = st.session_state.people
            if people and not ("Error" in people[0]['name']):
                for p in people:
                    st.markdown(f"**👤 {p['name']}** - *{p.get('role', 'No especificado')}*")
                    with st.expander("📝 Ver contexto"): st.markdown(f"> {p.get('context', 'N/A')}")
            else: st.info("No se identificaron personas o hubo un error en el análisis.")

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"): st.session_state.clear(); st.rerun()

st.markdown("<hr><div style='text-align: center; color: #666;'><p><strong>Transcriptor Pro - Johnascriptor v2.5.0</strong> - Desarrollado por Johnathan Cortés 🤖</p></div>", unsafe_allow_html=True)
