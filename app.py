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

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES AMPLIADO Y MEJORADO ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    r'\badministraci(?!ón\b)\b': 'administración', r'\bAdministraci(?!ón\b)\b': 'Administración',
    r'\bcomunicaci(?!ón\b)\b': 'comunicación', r'\bComunicaci(?!ón\b)\b': 'Comunicación',
    r'\bdeclaraci(?!ón\b)\b': 'declaración', r'\bDeclaraci(?!ón\b)\b': 'Declaración',
    r'\bdonaci(?!ón\b)\b': 'donación', r'\bDonaci(?!ón\b)\b': 'Donación',
    r'\beducaci(?!ón\b)\b': 'educación', r'\bEducaci(?!ón\b)\b': 'Educación',
    r'\bfundaci(?!ón\b)\b': 'fundación', r'\bFundaci(?!ón\b)\b': 'Fundación',
    r'\bimplementaci(?!ón\b)\b': 'implementación', r'\bImplementaci(?!ón\b)\b': 'Implementación',
    r'\binformaci(?!ón\b)\b': 'información', r'\bInformaci(?!ón\b)\b': 'Información',
    r'\binscripci(?!ón\b)\b': 'inscripción', r'\bInscripci(?!ón\b)\b': 'Inscripción',
    r'\binvestigaci(?!ón\b)\b': 'investigación', r'\bInvestigaci(?!ón\b)\b': 'Investigación',
    r'\bnaci(?!ón\b)\b': 'nación', r'\bNaci(?!ón\b)\b': 'Nación',
    r'\bnavegaci(?!ón\b)\b': 'navegación', r'\bNavegaci(?!ón\b)\b': 'Navegación',
    r'\boperaci(?!ón\b)\b': 'operación', r'\bOperaci(?!ón\b)\b': 'Operación',
    r'\bopini(?!ón\b)\b': 'opinión', r'\bOpini(?!ón\b)\b': 'Opinión',
    r'\borganizaci(?!ón\b)\b': 'organización', r'\bOrganizaci(?!ón\b)\b': 'Organización',
    r'\bparticipaci(?!ón\b)\b': 'participación', r'\bParticipaci(?!ón\b)\b': 'Participación',
    r'\bpoblaci(?!ón\b)\b': 'población', r'\bPoblaci(?!ón\b)\b': 'Población',
    r'\bprotecci(?!ón\b)\b': 'protección', r'\bProtecci(?!ón\b)\b': 'Protección',
    r'\brelaci(?!ón\b)\b': 'relación', r'\bRelaci(?!ón\b)\b': 'Relación',
    r'\breuni(?!ón\b)\b': 'reunión', r'\bReuni(?!ón\b)\b': 'Reunión',
    r'\bresoluci(?!ón\b)\b': 'resolución', r'\bResoluci(?!ón\b)\b': 'Resolución',
    r'\bsanci(?!ón\b)\b': 'sanción', r'\bSanci(?!ón\b)\b': 'Sanción',
    r'\bsituaci(?!ón\b)\b': 'situación', r'\bSituaci(?!ón\b)\b': 'Situación',
    r'\bCancerolog(?!ía\b)\b': 'Cancerología', r'\bCancerolog(?!ía\b)\b': 'Cancerología',
    r'\bcompañí(?!a\b)\b': 'compañía', r'\bCompañí(?!a\b)\b': 'Compañía',
    r'\beconomí(?!a\b)\b': 'economía', r'\bEconomí(?!a\b)\b': 'Economía',
    r'\benergí(?!a\b)\b': 'energía', r'\bEnergí(?!a\b)\b': 'Energía',
    r'\bgeografí(?!a\b)\b': 'geografía', r'\bGeografí(?!a\b)\b': 'Geografía',
    r'\bmetodolog(?!ía\b)\b': 'metodología', r'\bMetodolog(?!ía\b)\b': 'Metodología',
    r'\boncol(?!ógica\b)\b': 'oncológica', r'\bOncol(?!ógica\b)\b': 'Oncológica',
    r'\bpolític(?!a\b)\b': 'política', r'\bPolític(?!a\b)\b': 'Política',
    r'\bRepúblic(?!a\b)\b': 'República', r'\brepúblic(?!a\b)\b': 'república',
    r'\btecnolog(?!ía\b)\b': 'tecnología', r'\bTecnolog(?!ía\b)\b': 'Tecnología',
    r'\bAméric(?!a\b)\b': 'América',
    r'\bBogot(?!á\b)\b': 'Bogotá',
    r'\bMéxic(?!o\b)\b': 'México',
    r'\bPer\b': 'Perú',
    r'\badem(?!ás\b)\b': 'además', r'\bAdem(?!ás\b)\b': 'Además',
    r'\btambi(?!én\b)\b': 'también', r'\bTambi(?!én\b)\b': 'También',
    r'\búltim(?!o\b)\b': 'último', r'\bÚltim(?!o\b)\b': 'Último',
    r'\bdí\b': 'día', r'\bDí\b': 'Día',
    r'\bmiércole\b': 'miércoles', r'\bMiércole\b': 'Miércoles',
    r'\bdocumenta\b': 'documental', r'\bDocumenta\b': 'Documental',
    r'\bsostenib\b': 'sostenible', r'\bSostenib\b': 'Sostenible',
    r'\bentretenimient\b': 'entretenimiento', r'\bEntretenimient\b': 'Entretenimiento',
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué',
    r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde',
    r'\b(E|e)l\s(es|fue|será)\b': r'\1l \2', r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES ---
def scroll_to_top():
    js = '''<script>window.parent.document.querySelector(".main").scrollTop = 0;</script>'''
    components.html(js, height=0, width=0)

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
    lines = [f"[{format_timestamp(seg.get('start', 0))}] --> [{format_timestamp(seg.get('end', 0))}] {seg.get('text', '').strip()}" for seg in data.segments if isinstance(seg, dict)]
    return "\n".join(lines)

def clean_transcription_artifacts(text):
    """Removes common, non-verbal artifacts from transcriptions."""
    if not text: return ""
    # Remove "Subtitulado por..." and similar patterns, usually at the end of the text.
    cleaned_text = re.sub(r'subtitulado por\s+.*?[.]?\s*$', '', text, flags=re.IGNORECASE | re.DOTALL)
    return cleaned_text.strip()

def fix_spanish_encoding(text):
    if not text: return ""
    result = text
    encoding_fixes = {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã‘': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    
    result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result, flags=re.IGNORECASE)
    
    result = result.strip()
    if not result: return ""
    
    result = result[0].upper() + result[1:]
    result = re.sub(r'(?<=[.?!]\s)\s*([a-z])', lambda m: m.group(1).upper(), result)
    
    return result

def check_transcription_quality(text):
    if not text: return []
    issues = []
    if any(char in text for char in ['Ã', 'Â']):
        issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática.")
    if re.search(r'\b(qu|sostenib|fundaci|informaci)\s', text, re.IGNORECASE):
        issues.append("ℹ️ Se aplicaron correcciones automáticas de tildes y palabras cortadas.")
    return issues

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---
def convert_video_to_audio(video_bytes, video_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp_video:
            tmp_video.write(video_bytes); video_path = tmp_video.name
        audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
        with VideoFileClip(video_path) as video:
            video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None)
        with open(audio_path, 'rb') as f: audio_bytes = f.read()
        os.unlink(video_path); os.unlink(audio_path)
        return audio_bytes, True
    except Exception: return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes); audio_path = tmp_audio.name
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        with AudioFileClip(audio_path) as audio:
            audio.write_audiofile(compressed_path, codec='mp3', bitrate='96k', verbose=False, logger=None)
        with open(compressed_path, 'rb') as f: compressed_bytes = f.read()
        os.unlink(audio_path); os.unlink(compressed_path)
        return compressed_bytes
    except Exception: return audio_bytes

def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS ---
def improve_transcription_with_llm(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un experto editor y corrector de textos en español. Tu tarea es corregir la siguiente transcripción de audio. Reglas estrictas: 1. Corrige todos los errores de ortografía y gramática. 2. Añade tildes faltantes. 3. Une palabras que hayan sido cortadas incorrectamente. 4. No alteres el significado original ni añadas información que no esté en el texto. 5. No elimines contenido. 6. Devuelve únicamente el texto corregido, sin ninguna introducción ni comentario."},
                {"role": "user", "content": f"Por favor, corrige el siguiente texto:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.1, max_tokens=4096)
        return chat_completion.choices[0].message.content
    except Exception as e:
        st.warning(f"⚠️ No se pudo aplicar la corrección con IA: {str(e)}. Se usará la corrección estándar.")
        return transcription_text

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes profesionales y concisos en un solo párrafo. Mantén todas las tildes y acentos correctos en español."},
                {"role": "user", "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) del siguiente texto. Ve directo al contenido, sin introducciones. Mantén todas las tildes correctas:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500)
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Eres un asistente experto en análisis de contenido. Responde preguntas sobre la transcripción proporcionada de manera precisa, concisa y profesional. Reglas importantes:\n- Basa tus respuestas ÚNICAMENTE en la información de la transcripción\n- Si la información no está en la transcripción, indícalo claramente\n- Mantén todas las tildes y acentos correctos en español\n- Sé específico y cita partes relevantes cuando sea apropiado\n- Si te hacen una pregunta de seguimiento, considera el contexto de la conversación anterior"}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]}); messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Transcripción completa del audio:\n---\n{transcription_text}\n---\nPregunta: {question}\nResponde basándote exclusivamente en la transcripción anterior."})
        chat_completion = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant", temperature=0.2, max_tokens=800)
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {str(e)}"

def extract_quotes(segments):
    quotes = []; quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró']
    if not segments: return []
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict): continue
        text = seg.get('text', '').strip(); text_lower = text.lower(); start_time = seg.get('start')
        if start_time is None: continue
        has_quotes = '"' in text or '«' in text or '»' in text; has_declaration = any(keyword in text_lower for keyword in quote_keywords)
        if has_quotes or has_declaration:
            context_before = segments[i-1].get('text', '').strip() if i > 0 and isinstance(segments[i-1], dict) else ""
            context_after = segments[i+1].get('text', '').strip() if i < len(segments) - 1 and isinstance(segments[i+1], dict) else ""
            full_context = f"{context_before} {text} {context_after}".strip()
            quotes.append({'time': format_timestamp(start_time), 'text': text, 'full_context': full_context, 'start': start_time, 'type': 'quote' if has_quotes else 'declaration'})
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True); return quotes[:10]

def extract_entities(transcription_text, client, entity_type):
    if entity_type == 'people':
        system_prompt = 'Eres un analista experto en transcripciones de noticias. Tu tarea es identificar a todas las personas mencionadas por su nombre y, si se especifica, su cargo o rol. Debes devolver la información en formato JSON. El JSON debe ser una lista de objetos. Cada objeto debe tener tres claves: "name", "role" y "context".\n- "name": El nombre completo de la persona.\n- "role": El cargo o rol asociado (ej: "Presidente", "Director de la Fundación", "Analista"). Si no se menciona un rol, usa el valor "No especificado".\n- "context": La frase exacta de la transcripción donde se menciona a la persona y su rol.\nAsegúrate de que el JSON esté bien formado.'
        user_prompt = f"Analiza la siguiente transcripción y extrae las personas y sus roles. Formatea la salida como una lista JSON. Aquí está la transcripción:\n\n{transcription_text}"
        error_response = [{"name": "Error de API", "role": "", "context": ""}]
    else: # brands
        system_prompt = 'Eres un analista experto en identificar entidades en textos. Tu tarea es extraer todas las marcas comerciales, nombres de empresas o productos mencionados. Debes devolver la información en formato JSON. El JSON debe ser una lista de objetos, donde cada objeto tiene dos claves: "brand" y "context".\n- "brand": El nombre de la marca o empresa.\n- "context": La frase exacta de la transcripción donde se menciona la marca.\nAsegúrate de que el JSON esté bien formado y no incluyas marcas genéricas o dudosas.'
        user_prompt = f"Analiza la siguiente transcripción y extrae las marcas. Formatea la salida como una lista JSON. Transcripción:\n\n{transcription_text}"
        error_response = [{"brand": "Error de API", "context": ""}]
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            model="llama-3.1-8b-instant", temperature=0.1, max_tokens=1024, response_format={"type": "json_object"})
        response_content = chat_completion.choices[0].message.content; data = json.loads(response_content)
        if isinstance(data, list): return data
        for key in data:
            if isinstance(data.get(key), list): return data[key]
        return []
    except json.JSONDecodeError:
        error_response[0].update({"context": "El modelo no devolvió un JSON válido.", "name" if entity_type == 'people' else "brand": "Error de Análisis"})
        return error_response
    except Exception as e:
        error_response[0].update({"context": str(e)})
        return error_response

def get_extended_context(segments, match_index, context_range=2):
    if not segments: return []
    start_idx = max(0, match_index - context_range); end_idx = min(len(segments), match_index + context_range + 1)
    context_segments = []
    for i in range(start_idx, end_idx):
        seg = segments[i]
        if isinstance(seg, dict):
            is_match = (i == match_index); start_time = seg.get('start', 0); text = seg.get('text', '').strip()
            context_segments.append({'text': text, 'time': format_timestamp(start_time), 'start': start_time, 'is_match': is_match})
    return context_segments

def export_to_srt(data):
    srt_content = []
    if not hasattr(data, 'segments') or not data.segments: return ""
    for i, seg in enumerate(data.segments, 1):
        if not isinstance(seg, dict): continue
        start_time = timedelta(seconds=seg.get('start', 0)); end_time = timedelta(seconds=seg.get('end', 0))
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        text = seg.get('text', '').strip()
        srt_content.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")
with st.sidebar:
    st.header("⚙️ Configuración"); model_option = st.selectbox("Modelo de Transcripción", ["whisper-large-v3"], index=0); language = st.selectbox("Idioma", ["es"], index=0); temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0.0 para máxima precisión")
    st.markdown("---"); st.subheader("🎯 Análisis Inteligente"); enable_tilde_fix = st.checkbox("✨ Corrección gramatical y de tildes", value=True, help="Repara y mejora la gramática, puntuación y capitalización."); enable_llm_fix = st.checkbox("🧠 Corrección avanzada con IA", value=False, help="Usa Llama-3.1 para una revisión más profunda."); enable_summary = st.checkbox("📝 Generar resumen", value=True); enable_quotes = st.checkbox("💬 Identificar citas", value=True); enable_people = st.checkbox("👤 Extraer personas", value=True); enable_brands = st.checkbox("🏢 Extraer Marcas", value=True)
    st.markdown("---"); st.subheader("🔍 Búsqueda Contextual"); context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    st.markdown("---"); st.subheader("🔧 Procesamiento de Audio"); 
    if MOVIEPY_AVAILABLE: st.info("💡 MP4 > 25MB se convertirán a audio."); compress_audio_option = st.checkbox("📦 Comprimir audio", value=False)
    else: st.warning("⚠️ MoviePy no disponible."); compress_audio_option = False
    st.markdown("---"); st.info("💡 Formatos: MP3, MP4, WAV, etc."); st.success("✅ API Key configurada")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1: uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.clear(); st.session_state.audio_start_time = 0
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue(); original_size = get_file_size_mb(file_bytes)
                if os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4', '.mpeg', '.webm'] and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Convirtiendo video..."): file_bytes, _ = convert_video_to_audio(file_bytes, uploaded_file.name)
                if compress_audio_option and MOVIEPY_AVAILABLE:
                    with st.spinner("📦 Comprimiendo audio..."): file_bytes = compress_audio(file_bytes, uploaded_file.name)
                
                st.session_state.uploaded_audio_bytes = file_bytes; client = Groq(api_key=api_key)
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp: tmp.write(file_bytes); tmp_file_path = tmp.name
                with st.spinner("🔄 Transcribiendo con IA..."):
                    with open(tmp_file_path, "rb") as audio_file:
                        spanish_prompt = "Transcripción precisa en español. Presta máxima atención a las tildes, puntuación (¿?, ¡!) y mayúsculas. Transcribe textualmente sin omitir nada."
                        transcription = client.audio.transcriptions.create(file=(uploaded_file.name, audio_file.read()), model=model_option, temperature=temperature, language=language, response_format="verbose_json", prompt=spanish_prompt if language == "es" else None)
                os.unlink(tmp_file_path)
                
                raw_text = clean_transcription_artifacts(transcription.text)
                transcription_text = raw_text
                
                if language == "es":
                    if enable_llm_fix:
                        with st.spinner("🧠 Aplicando corrección avanzada con IA..."): transcription_text = improve_transcription_with_llm(raw_text, client)
                    elif enable_tilde_fix:
                        with st.spinner("✨ Aplicando correcciones gramaticales..."): transcription_text = fix_spanish_encoding(raw_text)
                
                if hasattr(transcription, 'segments') and transcription.segments:
                    for segment in transcription.segments:
                        if isinstance(segment, dict) and 'text' in segment:
                            cleaned_seg_text = clean_transcription_artifacts(segment['text'])
                            segment['text'] = fix_spanish_encoding(cleaned_seg_text) if enable_tilde_fix else cleaned_seg_text
                
                st.session_state.transcription = transcription_text; st.session_state.transcription_data = transcription;
                analysis_text = st.session_state.transcription

                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary: st.session_state.summary = generate_summary(analysis_text, client)
                    if enable_quotes and hasattr(transcription, 'segments'): st.session_state.quotes = extract_quotes(transcription.segments)
                    if enable_people: st.session_state.people = extract_entities(analysis_text, client, 'people')
                    if enable_brands: st.session_state.brands = extract_entities(analysis_text, client, 'brands')

                st.success("✅ ¡Transcripción y análisis completados!"); scroll_to_top(); st.balloons()
            except Exception as e: st.error(f"❌ Error durante la transcripción: {str(e)}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---"); st.subheader("🎧 Reproduce y Analiza el Contenido")
    if st.session_state.uploaded_audio_bytes: st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.get('audio_start_time', 0))
    else: st.warning("⚠️ No hay audio disponible.")

    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo", "💬 Citas y Declaraciones"]
    if enable_people: tab_titles.append("👥 Personas Clave")
    if enable_brands: tab_titles.append("🏢 Marcas Mencionadas")
    tabs = st.tabs(tab_titles)

    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"; MATCH_LINE_STYLE = "background-color: #1e3a5f; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #fca311;"; CONTEXT_LINE_STYLE = "background-color: #1a1a1a; padding: 0.6rem; border-radius: 4px; color: #b8b8b8; border-left: 2px solid #404040;"; TRANSCRIPTION_BOX_STYLE = "background-color: #0E1117; color: #FAFAFA; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; line-height: 1.7;"
        col_search1, col_search2 = st.columns([4, 1])
        with col_search1: search_query = st.text_input("🔎 Buscar en la transcripción:", key="search_box")
        with col_search2: st.write(""); st.button("🗑️ Limpiar", on_click=lambda: st.session_state.update(search_box=""), use_container_width=True)
        if search_query and hasattr(st.session_state.transcription_data, 'segments'):
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments; pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matching_indices = [i for i, seg in enumerate(segments) if isinstance(seg, dict) and pattern.search(seg.get('text', ''))]
                if not matching_indices: st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)")
                    for result_num, match_idx in enumerate(matching_indices, 1):
                        context_segments = get_extended_context(segments, match_idx, context_lines)
                        for ctx_seg in context_segments:
                            col_t, col_c = st.columns([0.15, 0.85]); 
                            col_t.button(f"▶️ {ctx_seg['time']}", key=f"play_{match_idx}_{ctx_seg['start']}", on_click=set_audio_time, args=(ctx_seg['start'],))
                            highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', ctx_seg['text'])
                            style = MATCH_LINE_STYLE if ctx_seg['is_match'] else CONTEXT_LINE_STYLE
                            col_c.markdown(f"<div style='{style}'>{highlighted_text}</div>", unsafe_allow_html=True)
                        if result_num < len(matching_indices): st.markdown("---")
        st.markdown("**📄 Transcripción completa:**"); transcription_html = st.session_state.transcription.replace('\n', '<br>')
        if search_query: transcription_html = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', transcription_html)
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{transcription_html}</div>', unsafe_allow_html=True); st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1: st.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        with col_d2: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", use_container_width=True)
        with col_d3: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", use_container_width=True)
        with col_d4: create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo"); st.markdown(st.session_state.summary); st.write("")
            col_s1, col_s2 = st.columns([3, 1]); col_s1.download_button("💾 Descargar Resumen", st.session_state.summary, "resumen.txt", use_container_width=True); col_s2.button("📋 Copiar Resumen", on_click=lambda: st.toast("Copiado!"), use_container_width=True)
            st.markdown("---"); st.markdown("### 💭 Haz preguntas sobre el contenido")
            if 'qa_history' not in st.session_state: st.session_state.qa_history = []
            for qa in st.session_state.qa_history:
                st.markdown(f"**🙋 Pregunta:** {qa['question']}"); st.markdown(f"**🤖 Respuesta:** {qa['answer']}")
            with st.form(key="q_form", clear_on_submit=True):
                user_q = st.text_area("Escribe tu pregunta:", height=100); submitted = st.form_submit_button("🚀 Enviar")
                if submitted and user_q:
                    with st.spinner("🤔 Analizando..."):
                        client = Groq(api_key=api_key); answer = answer_question(user_q, st.session_state.transcription, client, st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': user_q, 'answer': answer}); st.rerun()
        else: st.info("📝 Resumen no generado.")

    with tabs[2]:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones Relevantes")
            for idx, quote in enumerate(st.session_state.quotes):
                st.markdown("🗣️ **Cita Textual**" if quote['type'] == 'quote' else "📢 **Declaración**")
                col_q1, col_q2 = st.columns([0.12, 0.88]); col_q1.button(f"▶️ {quote['time']}", key=f"q_{idx}", on_click=set_audio_time, args=(quote['start'],))
                with col_q2: st.markdown(f"*{quote['text']}*"); st.expander("📄 Ver contexto").markdown(quote['full_context'])
                st.markdown("---")
        else: st.info("💬 No se identificaron citas relevantes.")
    
    tab_index = 3
    if enable_people and tab_index < len(tabs):
        with tabs[tab_index]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            people_data = st.session_state.get('people', []); valid_people = [p for p in people_data if isinstance(p, dict) and p.get('name')]
            if valid_people and "Error" not in valid_people[0].get('name', ''):
                st.caption(f"Se identificaron {len(valid_people)} personas clave.")
                for i, person in enumerate(valid_people):
                    name = str(person.get('name', 'N/A')); role = str(person.get('role', 'N/A')); context = str(person.get('context', 'N/A'))
                    st.markdown(f"**👤 {name}** - *{role}*")
                    with st.expander("📝 Ver contexto", key=f"p_ctx_{i}"): st.markdown(f"> {context}")
            elif valid_people: st.error(f"**{valid_people[0].get('name', 'Error')}**: {valid_people[0].get('context', 'Sin detalles.')}")
            else: st.info("👤 No se identificaron personas en el audio.")
            tab_index += 1

    if enable_brands and tab_index < len(tabs):
        with tabs[tab_index]:
            st.markdown("### 🏢 Marcas Mencionadas")
            brands_data = st.session_state.get('brands', []); valid_brands = [b for b in brands_data if isinstance(b, dict) and b.get('brand')]
            if valid_brands and "Error" not in valid_brands[0].get('brand', ''):
                st.caption(f"Se identificaron {len(valid_brands)} marcas.")
                for i, item in enumerate(valid_brands):
                    brand = str(item.get('brand', 'N/A')); context = str(item.get('context', 'N/A'))
                    st.markdown(f"**🏢 {brand}**")
                    with st.expander("📝 Ver contexto", key=f"b_ctx_{i}"): st.markdown(f"> {context}")
            elif valid_brands: st.error(f"**{valid_brands[0].get('brand', 'Error')}**: {valid_brands[0].get('context', 'Sin detalles.')}")
            else: st.info("🏢 No se identificaron marcas en el audio.")

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"): st.session_state.clear(); st.rerun()

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p><strong>Transcriptor Pro - Johnascriptor - v3.3.0 (Estable)</strong> - Desarrollado por Johnathan Cortés 🤖</p>
    <p style='font-size: 0.85rem;'>✨ Con sistema de corrección gramatical, limpieza de artefactos y análisis de entidades</p>
</div>
""", unsafe_allow_html=True)
