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

if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()


### MEJORA 1: DICCIONARIO DE CORRECCIONES HIPER-ESPECIALIZADO ###
# Añadimos reglas de "cirugía de precisión" para errores comunes reportados.
SPANISH_WORD_CORRECTIONS = {
    # --- ERRORES ESPECÍFICOS Y CONTEXTUALES ---
    # Corrige "mi 25 de septiembre" a "miércoles 25 de septiembre"
    r'\bmi (?=\d{1,2} de)': 'miércoles ',
    # Corrige "S Juan Manuel" a "Soy Juan Manuel" o "Es Juan Manuel"
    r'\bS (?=[A-Z][a-z])': 'Soy ', 
    
    # --- INTERROGATIVOS / EXCLAMATIVOS (MUY ALTA PRIORIDAD) ---
    r'\bqu\s+se\b': 'qué se',
    r'\bqu\s+es\b': 'qué es',
    r'\bqu\s+fue\b': 'qué fue',
    r'\bqu\s+hay\b': 'qué hay',
    r'\bqu\s+pasa\b': 'qué pasa',
    r'\bqu\s+tal\b': 'qué tal',
    r'\bQu\s+se\b': 'Qué se',
    r'\bQu\s+es\b': 'Qué es',
    r'\bPor\s+qu(?!\s+[eé])\b': 'Por qué',
    r'\bpor\s+qu(?!\s+[eé])\b': 'por qué',

    # --- VERBOS EN PASADO (PRETÉRITO) - ERROR MUY COMÚN ---
    r'\blanz(?=\s|$)': 'lanzó',
    r'\bLanz(?=\s|$)': 'Lanzó',
    r'\bpublic(?=\s|$)': 'publicó',
    r'\bPublic(?=\s|$)': 'Publicó',
    r'\bpresent(?=\s|$)': 'presentó',
    r'\bPresent(?=\s|$)': 'Presentó',
    r'\banunci(?=\s|$)': 'anunció',
    r'\bAnunci(?=\s|$)': 'Anunció',
    r'\bafirm(?=\s|$)': 'afirmó',
    r'\bAfirm(?=\s|$)': 'Afirmó',
    r'\bexplic(?=\s|$)': 'explicó',
    r'\bExplic(?=\s|$)': 'Explicó',
    r'\bconfirm(?=\s|$)': 'confirmó',
    r'\bConfirm(?=\s|$)': 'Confirmó',
    r'\bmostr(?=\s|$)': 'mostró',
    r'\bMostr(?=\s|$)': 'Mostró',
    r'\bse\s+lanz\b': 'se lanzó', # Combinación común

    # --- PALABRAS CORTADAS COMUNES (-CIÓN) ---
    r'\bfundaci(?=\s|$)': 'fundación', 'r\bFundaci(?=\s|$)': 'Fundación',
    r'\binformaci(?=\s|$)': 'información', r'\bInformaci(?=\s|$)': 'Información',
    r'\bsituaci(?=\s|$)': 'situación', r'\bSituaci(?=\s|$)': 'Situación',
    r'\bdeclaraci(?=\s|$)': 'declaración', r'\bDeclaraci(?=\s|$)': 'Declaración',
    r'\bnaci(?=\s|$)': 'nación', r'\bNaci(?=\s|$)': 'Nación',
    r'\bpoblaci(?=\s|$)': 'población', r'\bPoblaci(?=\s|$)': 'Población',
    r'\borganizaci(?=\s|$)': 'organización', r'\bOrganizaci(?=\s|$)': 'Organización',
    r'\bparticipaci(?=\s|$)': 'participación', r'\bParticipaci(?=\s|$)': 'Participación',
    r'\binvestigaci(?=\s|$)': 'investigación', r'\bInvestigaci(?=\s|$)': 'Investigación',
    r'\beducaci(?=\s|$)': 'educación', r'\bEducaci(?=\s|$)': 'Educación',
    r'\bcomunicaci(?=\s|$)': 'comunicación', r'\bComunicaci(?=\s|$)': 'Comunicación',
    r'\boperaci(?=\s|$)': 'operación', r'\bOperaci(?=\s|$)': 'Operación',
    r'\badministraci(?=\s|$)': 'administración', r'\bAdministraci(?=\s|$)': 'Administración',

    # --- PALABRAS CORTADAS COMUNES (-ÍA) ---
    r'\bcompa(?=\s|$)': 'compañía', r'\bCompa(?=\s|$)': 'Compañía',
    r'\beconom(?=\s|$)': 'economía', r'\bEconom(?=\s|$)': 'Economía',
    r'\benerg(?=\s|$)': 'energía', r'\bEnerg(?=\s|$)': 'Energía',
    r'\bpolic(?=\s|$)': 'policía', r'\bPolic(?=\s|$)': 'Policía',
    
    # --- OTRAS PALABRAS COMUNES ---
    r'\bpolitic(?=\s|$)': 'política', r'\bPolitic(?=\s|$)': 'Política',
    r'\bpai(?=\s|$)': 'país', r'\bPai(?=\s|$)': 'País',
    r'\bda(?=\s|$)': 'día', r'\bDa(?=\s|$)': 'Día',
    r'\bmas\b': 'más', r'\bMas\b': 'Más',
    r'\besta(?=\s|$)': 'está', r'\bEsta(?=\s|$)': 'Está',
    r'\bcolombia(?=\s|$)': 'Colombia',
    r'\bamazonia(?=\s|$)': 'Amazonía',
    r'\bentretenim(?=\s|$)': 'entretenimiento', r'\bEntretenim(?=\s|$)': 'Entretenimiento',
    r'\bsostenib(?=\s|$)': 'sostenible', r'\bSostenib(?=\s|$)': 'Sostenible',
    r'\bdocument(?=\s|$)': 'documental', r'\bDocument(?=\s|$)': 'Documental',
}


# --- FUNCIONES AUXILIARES ORIGINALES ---

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">
        📋 Copiar Todo
    </button>
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
    </script>
    """
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [
        f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}"
        for seg in data.segments
    ]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    """
    Corrige problemas de encoding, palabras cortadas y otros artefactos en español.
    Sigue un proceso de varios pasos para mayor precisión.
    """
    if not text:
        return text
    
    result = text
    
    # PASO 1: Corregir problemas de encoding UTF-8 (si los hubiera)
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'
    }
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)

    # PASO 2: Aplicar todas las correcciones del diccionario robusto
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # PASO 3: Limpieza de sílabas o letras repetidas (artefacto común)
    result = re.sub(r'([a-zA-ZáéíóúñÁÉÍÓÚÑ])\1{2,}', r'\1', result) 
    result = re.sub(r'\b(\w{3,})(\1){1,}\b', r'\1', result)

    return result

def check_transcription_quality(text):
    if not text: return []
    issues = []
    if any(char in text for char in ['Ã', 'Â']):
        issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática")
    if len(re.findall(r'\bqu\s', text, re.IGNORECASE)) > 0:
        issues.append(f"ℹ️ Se aplicaron correcciones automáticas de tildes y palabras cortadas.")
    return issues

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
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        os.unlink(video_path)
        os.unlink(audio_path)
        return audio_bytes, True
    except Exception as e:
        st.warning(f"Error convirtiendo video a audio: {e}")
        return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes)
            audio_path = tmp_audio.name
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(compressed_path, codec='mp3', bitrate='96k', verbose=False, logger=None)
        audio.close()
        with open(compressed_path, 'rb') as f:
            compressed_bytes = f.read()
        os.unlink(audio_path)
        os.unlink(compressed_path)
        return compressed_bytes
    except Exception as e:
        st.warning(f"Error comprimiendo audio: {e}")
        return audio_bytes

def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS ---

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes en formato de párrafo corrido, profesionales y concisos. IMPORTANTE: Mantén todas las tildes y acentos correctos en español."},
                {"role": "user", "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) sobre el siguiente contenido. No uses bullet points ni listas. Ve directo al contenido. Mantén todas las tildes correctas:\n\n{transcription_text}"}
            ],
            model="llama-3.1-70b-versatile", temperature=0.3, max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {str(e)}"

def extract_quotes(segments):
    quotes = []
    quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró', 'confirmó']
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        has_quotes = '"' in text or '«' in text or '»' in text
        has_declaration = any(keyword in text.lower() for keyword in quote_keywords)
        if has_quotes or has_declaration:
            context_before = segments[i-1]['text'].strip() if i > 0 else ""
            context_after = segments[i+1]['text'].strip() if i < len(segments) - 1 else ""
            full_context = f"{context_before} {text} {context_after}".strip()
            quotes.append({'time': format_timestamp(seg['start']), 'text': text, 'full_context': full_context, 'start': seg['start'], 'type': 'quote' if has_quotes else 'declaration'})
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)
    return quotes[:10]

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start_hms = format_timestamp(seg['start'])
        start_ms = int((seg['start'] % 1) * 1000)
        end_hms = format_timestamp(seg['end'])
        end_ms = int((seg['end'] % 1) * 1000)
        start_srt = f"{start_hms},{start_ms:03d}"
        end_srt = f"{end_hms},{end_ms:03d}"
        text = seg['text'].strip()
        srt_content.append(f"{i}\n{start_srt} --> {end_srt}\n{text}\n")
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---

st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"], 0, help="Máxima precisión para español.")
    language = st.selectbox("Idioma", ["es", "en"], 0)
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0.0 para máxima precisión")
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas", value=True)
    enable_tilde_fix = st.checkbox("✨ Corrección de español (Recomendado)", value=True, help="Repara palabras cortadas y acentos.")
    st.markdown("---")
    st.subheader("🔧 Procesamiento de Audio")
    if MOVIEPY_AVAILABLE:
        st.info("💡 Videos >25 MB se convertirán a MP3.")
        compress_audio_option = st.checkbox("📦 Comprimir audio", value=False)
    else:
        st.warning("⚠️ MoviePy no instalado. Conversión de video no disponible.")
        compress_audio_option = False
    st.markdown("---")
    st.info("💡 **Formatos:** MP3, MP4, WAV, WEBM, M4A")
    st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.audio_start_time = 0
        st.session_state.last_search = ""
        st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                original_size = get_file_size_mb(file_bytes)
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                is_video = file_extension in ['.mp4', '.mpeg', '.webm']
                if is_video and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Video de {original_size:.2f} MB. Convirtiendo..."):
                        file_bytes, converted = convert_video_to_audio(file_bytes, uploaded_file.name)
                        if converted:
                            new_size = get_file_size_mb(file_bytes)
                            reduction = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
                            st.success(f"✅ Convertido: {original_size:.2f} MB → {new_size:.2f} MB (-{reduction:.1f}%)")
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo..."):
                        size_before = get_file_size_mb(file_bytes)
                        file_bytes = compress_audio(file_bytes, uploaded_file.name)
                        size_after = get_file_size_mb(file_bytes)
                        reduction = ((size_before - size_after) / size_before) * 100 if size_before > 0 else 0
                        st.success(f"✅ Comprimido: {size_before:.2f} MB → {size_after:.2f} MB (-{reduction:.1f}%)")
                st.session_state.uploaded_audio_bytes = file_bytes
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_file_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA... (puede tardar)"):
                    with open(tmp_file_path, "rb") as audio_file:
                        audio_content = audio_file.read()
                        safe_filename = uploaded_file.name.encode('latin-1', 'ignore').decode('latin-1')
                        
                        ### MEJORA 2: PROMPT CON EJEMPLOS ESPECÍFICOS ###
                        spanish_prompt = """Transcribe cuidadosamente en español de Latinoamérica. Reglas estrictas:
1.  **Interrogativos:** SIEMPRE con tilde: qué, por qué, cómo, cuándo.
2.  **Verbos en pasado:** Asegúrate de incluir la tilde final. Por ejemplo: "se lanzó", "publicó", "presentó", "afirmó".
3.  **Fechas y Nombres:** Transcribe "miércoles 25 de septiembre", no "mi 25 de septiembre". Transcribe "Soy Juan Manuel", no "S Juan Manuel".
4.  **Palabras completas:** Nunca cortes palabras. "información" (no "informaci"), "compañía" (no "compañi").
5.  **Nombres propios:** Colombia, Bogotá, Amazonía, Fundación Ford."""
                        
                        transcription = client.audio.transcriptions.create(
                            file=(safe_filename, audio_content), model=model_option, temperature=temperature,
                            language=language, response_format="verbose_json",
                            prompt=spanish_prompt if language == "es" else None
                        )
                
                os.unlink(tmp_file_path)
                
                if enable_tilde_fix and language == "es":
                    with st.spinner("✨ Aplicando correcciones avanzadas de español..."):
                        transcription_text = fix_spanish_encoding(transcription.text)
                        if hasattr(transcription, 'segments'):
                            for segment in transcription.segments:
                                segment['text'] = fix_spanish_encoding(segment['text'])
                        quality_issues = check_transcription_quality(transcription_text)
                        for issue in quality_issues: st.info(issue)
                else:
                    transcription_text = transcription.text
                
                st.session_state.transcription = transcription_text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis..."):
                    if enable_summary: st.session_state.summary = generate_summary(transcription_text, client)
                    if enable_quotes and hasattr(transcription, 'segments'): st.session_state.quotes = extract_quotes(transcription.segments)
                
                st.success("✅ ¡Transcripción y análisis completados!")
                st.balloons()
            except Exception as e: st.error(f"❌ Error en la transcripción: {e}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    st.write("")
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "📊 Resumen", "💬 Citas"])
    
    with tab1:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        TRANSCRIPTION_BOX_STYLE = "background-color: #0E1117; color: #FAFAFA; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; line-height: 1.7; white-space: pre-wrap; font-size: 0.95rem;"
        
        col_search1, col_search2 = st.columns([4, 1])
        with col_search1:
            search_query = st.text_input("🔎 Buscar en la transcripción:", value=st.session_state.get('last_search', ''), key=f"search_input_{st.session_state.get('search_counter', 0)}")
            if search_query != st.session_state.get('last_search', ''): st.session_state.last_search = search_query
        with col_search2:
            st.write("")
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query):
                st.session_state.last_search = ""
                st.session_state.search_counter += 1
                st.rerun()
        
        if search_query and hasattr(st.session_state.transcription_data, 'segments'):
            with st.expander("Resultados de la búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if not matching_indices: st.info("No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)")
                    indices_to_display = set(idx for i in matching_indices for idx in range(max(0, i-1), min(len(segments), i+2)))
                    last_index = -2
                    for i in sorted(list(indices_to_display)):
                        if i > last_index + 1: st.markdown("<div style='text-align:center; color: #555;'>[...]</div>", unsafe_allow_html=True)
                        segment = segments[i]
                        start_seconds = int(segment['start'])
                        text = segment['text'].strip()
                        col_ts, col_text = st.columns([0.2, 0.8], gap="small")
                        with col_ts:
                            if st.button(f"▶️ {format_timestamp(start_seconds)}", key=f"play_search_{i}", use_container_width=True):
                                st.session_state.audio_start_time = start_seconds
                                st.rerun()
                        with col_text:
                            highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', text) if i in matching_indices else f"<span style='color: #888;'>{text}</span>"
                            st.markdown(highlighted_text, unsafe_allow_html=True)
                        last_index = i
        
        st.markdown("**Transcripción completa:**")
        highlighted_transcription = re.sub(f'({re.escape(search_query)})', f'<span style="{HIGHLIGHT_STYLE}">\\1</span>', st.session_state.transcription, flags=re.IGNORECASE) if search_query else st.session_state.transcription
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{highlighted_transcription.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
        st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1: st.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", "text/plain", use_container_width=True)
        with col_d2: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "transcripcion_tiempos.txt", "text/plain", use_container_width=True)
        with col_d3: st.download_button("💾 SRT Subtítulos", export_to_srt(st.session_state.transcription_data), "subtitulos.srt", "application/x-subrip", use_container_width=True)
        with col_d4: create_copy_button(st.session_state.transcription)
    
    with tab2:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            st.write("")
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1: st.download_button("💾 Descargar Resumen", st.session_state.summary, "resumen.txt", "text/plain", use_container_width=True)
            with col_s2: create_copy_button(st.session_state.summary)
        else: st.info("📝 Resumen no generado.")
    
    with tab3:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones Relevantes")
            for idx, quote in enumerate(st.session_state.quotes):
                with st.container(border=True):
                    st.markdown("🗣️ **Cita Textual**" if quote['type'] == 'quote' else "📢 **Declaración**")
                    col_q1, col_q2 = st.columns([0.15, 0.85])
                    with col_q1:
                        if st.button(f"▶️ {quote['time']}", key=f"quote_{idx}"):
                            st.session_state.audio_start_time = int(quote['start'])
                            st.rerun()
                    with col_q2: st.markdown(f"*{quote['text']}*")
                    with st.expander("📄 Ver contexto completo"): st.caption(quote['full_context'])
        else: st.info("💬 No se identificaron citas.")
    
    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo", type="secondary"):
        for key in ["transcription", "transcription_data", "uploaded_audio_bytes", "audio_start_time", "summary", "quotes", "last_search"]:
            if key in st.session_state: del st.session_state[key]
        st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'>
<p><strong>Transcriptor Pro - Johnascriptor - v2.4</strong> - Desarrollado por Johnathan Cortés 🤖</p>
<p style='font-size: 0.85rem;'>✨ Con corrección de precisión para fechas y verbos en español</p>
</div>""", unsafe_allow_html=True)
