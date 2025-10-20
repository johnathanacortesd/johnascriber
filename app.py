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

# --- DICCIONARIO COMPLETO DE CORRECCIONES ESPAÑOLAS (SIN DUPLICACIÓN) ---
# IMPORTANTE: Los patrones aquí son más restrictivos para evitar duplicaciones

SPANISH_WORD_CORRECTIONS = {
    # Palabras terminadas en -ción (MUY COMÚN EN NOTICIAS)
    # Usar lookahead para evitar duplicar palabras ya corregidas
    r'\bqu\s+se\b': 'qué se',
    r'\bqu\s+es\b': 'qué es',
    r'\bqu\s+fue\b': 'qué fue',
    r'\bqu\s+hay\b': 'qué hay',
    r'\bqu\s+significa\b': 'qué significa',
    r'\bqu\s+pasa\b': 'qué pasa',
    r'\bPor\s+qu(?!\s+[eé])\b': 'Por qué',
    r'\bpor\s+qu(?!\s+[eé])\b': 'por qué',
    
    # Palabras cortadas comunes - SIN espacios adicionales al final
    # para evitar que se dupliquen en la siguiente iteración
    r'\bfundaci(?=\s|$)': 'fundación',
    r'\bFundaci(?=\s|$)': 'Fundación',
    r'\binformaci(?=\s|$)': 'información',
    r'\bInformaci(?=\s|$)': 'Información',
    r'\bsituaci(?=\s|$)': 'situación',
    r'\bSituaci(?=\s|$)': 'Situación',
    r'\bdeclaraci(?=\s|$)': 'declaración',
    r'\bDeclaraci(?=\s|$)': 'Declaración',
    r'\bnaci(?=\s|$)': 'nación',
    r'\bNaci(?=\s|$)': 'Nación',
    r'\bpoblaci(?=\s|$)': 'población',
    r'\bPoblaci(?=\s|$)': 'Población',
    r'\breuni(?=\s|$)': 'reunión',
    r'\bReuni(?=\s|$)': 'Reunión',
    r'\bopini(?=\s|$)': 'opinión',
    r'\bOpini(?=\s|$)': 'Opinión',
    r'\bresoluci(?=\s|$)': 'resolución',
    r'\bResoluci(?=\s|$)': 'Resolución',
    r'\borganizaci(?=\s|$)': 'organización',
    r'\bOrganizaci(?=\s|$)': 'Organización',
    r'\bprotecci(?=\s|$)': 'protección',
    r'\bProtecci(?=\s|$)': 'Protección',
    r'\bparticipaci(?=\s|$)': 'participación',
    r'\bParticipaci(?=\s|$)': 'Participación',
    r'\binvestigaci(?=\s|$)': 'investigación',
    r'\bInvestigaci(?=\s|$)': 'Investigación',
    r'\beducaci(?=\s|$)': 'educación',
    r'\bEducaci(?=\s|$)': 'Educación',
    r'\bsanci(?=\s|$)': 'sanción',
    r'\bSanci(?=\s|$)': 'Sanción',
    r'\bcomunicaci(?=\s|$)': 'comunicación',
    r'\bComunicaci(?=\s|$)': 'Comunicación',
    r'\boperaci(?=\s|$)': 'operación',
    r'\bOperaci(?=\s|$)': 'Operación',
    r'\brelaci(?=\s|$)': 'relación',
    r'\bRelaci(?=\s|$)': 'Relación',
    r'\bpoli(?=\s|$)': 'política',
    r'\bPoli(?=\s|$)': 'Política',
    r'\bcompa(?=\s|$)': 'compañía',
    r'\bCompa(?=\s|$)': 'Compañía',
    r'\beconom(?=\s|$)': 'economía',
    r'\bEconom(?=\s|$)': 'Economía',
    r'\bpai(?=\s|$)': 'país',
    r'\bPai(?=\s|$)': 'País',
    r'\bda(?=\s|$)': 'día',
    r'\bDa(?=\s|$)': 'Día',
    r'\bgeograf(?=\s|$)': 'geografía',
    r'\bGeograf(?=\s|$)': 'Geografía',
    
    # Más palabras con -ción
    r'\badministraci(?=\s|$)': 'administración',
    r'\bAdministraci(?=\s|$)': 'Administración',
    r'\bconservaci(?=\s|$)': 'conservación',
    r'\bConservaci(?=\s|$)': 'Conservación',
    r'\bconvenci(?=\s|$)': 'convención',
    r'\bConvenci(?=\s|$)': 'Convención',
    r'\bpresentaci(?=\s|$)': 'presentación',
    r'\bPresentaci(?=\s|$)': 'Presentación',
    r'\bimplementaci(?=\s|$)': 'implementación',
    r'\bImplementaci(?=\s|$)': 'Implementación',
    r'\bevaluaci(?=\s|$)': 'evaluación',
    r'\bEvaluaci(?=\s|$)': 'Evaluación',
    r'\bsoluci(?=\s|$)': 'solución',
    r'\bSoluci(?=\s|$)': 'Solución',
    r'\binstituci(?=\s|$)': 'institución',
    r'\bInstituci(?=\s|$)': 'Institución',
    r'\bcolaboraci(?=\s|$)': 'colaboración',
    r'\bColaboraci(?=\s|$)': 'Colaboración',
    r'\bseguridaci(?=\s|$)': 'seguridad',
    r'\bSeguridaci(?=\s|$)': 'Seguridad',
    
    # Palabras con -ía (sin espacios al final)
    r'\benergi(?=\s|$)': 'energía',
    r'\bEnergi(?=\s|$)': 'Energía',
    r'\bgaranti(?=\s|$)': 'garantía',
    r'\bGaranti(?=\s|$)': 'Garantía',
    r'\bhigieni(?=\s|$)': 'higiene',
    r'\bHigieni(?=\s|$)': 'Higiene',
    r'\btipologi(?=\s|$)': 'tipología',
    r'\bTipologi(?=\s|$)': 'Tipología',
    r'\bampliaci(?=\s|$)': 'ampliación',
    r'\bAmplicaci(?=\s|$)': 'Ampliación',
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

# --- FUNCIÓN MEJORADA: POST-PROCESAMIENTO PARA TILDES Y PALABRAS CORTADAS ---

def fix_spanish_encoding(text):
    """
    Corrige problemas de encoding y palabras cortadas en español.
    PRIORIZA la reparación de palabras cortadas antes de otros fixes.
    Evita duplicaciones usando lookahead y lookahead/behind.
    """
    if not text:
        return text
    
    result = text
    
    # PASO 1: Corregir problemas de encoding UTF-8
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        'Ã±': 'ñ', 'Ã': 'Ñ',
        'Â¿': '¿', 'Â¡': '¡',
    }
    
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    
    # PASO 1.5: LIMPIEZA DE DUPLICACIONES - Eliminar letras repetidas 3+ veces
    # Esto elimina "lalal", "ientoiento", etc.
    result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result)
    
    # PASO 2: Reparar palabras CORTADAS (qué, por qué, etc.)
    word_repairs = {
        r'\bqu\s+se\b': 'qué se',
        r'\bqu\s+es\b': 'qué es',
        r'\bqu\s+fue\b': 'qué fue',
        r'\bqu\s+hay\b': 'qué hay',
        r'\bqu\s+significa\b': 'qué significa',
        r'\bqu\s+pasa\b': 'qué pasa',
        r'\bqu\s+tal\b': 'qué tal',
        r'\bQu\s+se\b': 'Qué se',
        r'\bQu\s+es\b': 'Qué es',
        r'\bQu\s+fue\b': 'Qué fue',
        r'\bPor\s+qu(?!\s+[eé])\b': 'Por qué',
        r'\bpor\s+qu(?!\s+[eé])\b': 'por qué',
    }
    
    for pattern, replacement in word_repairs.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # PASO 3: Aplicar correcciones del diccionario (UNA SOLA VEZ)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        # count=1 para aplicar solo UNA VEZ por patrón
        result = re.sub(pattern, replacement, result, count=1, flags=re.IGNORECASE)
    
    # PASO 4: Limpieza final de palabras parcialmente duplicadas
    # Elimina "Documentalalal" -> "Documental", "Sosteniblelele" -> "Sostenible"
    cleanup_patterns = [
        (r'documentalalal', 'documental'),
        (r'Documentalalal', 'Documental'),
        (r'sosteniblelele', 'sostenible'),
        (r'Sosteniblelele', 'Sostenible'),
        (r'entretenimientoientoiento', 'entretenimiento'),
        (r'Entretenimientoientoiento', 'Entretenimiento'),
        (r'([a-záéíóúñ])\1{2,}', r'\1'),  # Eliminar cualquier duplicación triple
    ]
    
    for pattern, replacement in cleanup_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # PASO 5: Corregir palabras clave específicas que quedan sin tildes
    final_fixes = [
        (r'\bAmazon(?!í)\b', 'Amazonía'),
        (r'\bamazon(?!í)\b', 'amazonía'),
        (r'\bColombia(?!no)', 'Colombia'),
        (r'\sentretenim(?!iento)\b', ' entretenimiento'),
        (r'\bEntretenim(?!iento)\b', 'Entretenimiento'),
        (r'\bsostenib(?!le)\b', 'sostenible'),
        (r'\bSostenib(?!le)\b', 'Sostenible'),
        (r'\bdocument(?!al)\b', 'documental'),
        (r'\bDocument(?!al)\b', 'Documental'),
    ]
    
    for pattern, replacement in final_fixes:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result

def check_transcription_quality(text):
    """Detecta posibles problemas de encoding o tildes faltantes"""
    if not text:
        return []
    
    issues = []
    
    if any(char in text for char in ['Ã', 'Â', 'â', 'º', '°']):
        issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática")
    
    # Detectar si quedan duplicaciones triples (error de post-procesamiento)
    if re.search(r'([a-záéíóúñ])\1{2,}', text):
        issues.append("⚠️ Detectadas algunas palabras parcialmente duplicadas - Se aplicó limpieza")
    
    suspicious_patterns = [
        (r'\bqu\s+', 'palabras cortadas sin tilde'),
        (r'\bpor\s+qu\s+', 'palabras cortadas "por qué"'),
    ]
    
    suspicious_count = 0
    for pattern, _ in suspicious_patterns:
        suspicious_count += len(re.findall(pattern, text, re.IGNORECASE))
    
    if suspicious_count > 0:
        issues.append(f"ℹ️ Se aplicaron {suspicious_count} correcciones automáticas de tildes")
    
    return issues

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---

def convert_video_to_audio(video_bytes, video_filename):
    """Convierte video (MP4) a audio (MP3) con compresión"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp_video:
            tmp_video.write(video_bytes)
            video_path = tmp_video.name
        
        audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
        
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(
            audio_path,
            codec='mp3',
            bitrate='128k',
            verbose=False,
            logger=None
        )
        video.close()
        
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        
        os.unlink(video_path)
        os.unlink(audio_path)
        
        return audio_bytes, True
    except Exception as e:
        return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    """Comprime audio reduciendo bitrate"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes)
            audio_path = tmp_audio.name
        
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(
            compressed_path,
            codec='mp3',
            bitrate='96k',
            verbose=False,
            logger=None
        )
        audio.close()
        
        with open(compressed_path, 'rb') as f:
            compressed_bytes = f.read()
        
        os.unlink(audio_path)
        os.unlink(compressed_path)
        
        return compressed_bytes
    except Exception as e:
        return audio_bytes

def get_file_size_mb(file_bytes):
    """Calcula el tamaño del archivo en MB"""
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS ---

def generate_summary(transcription_text, client):
    """Genera un resumen inteligente usando Groq LLaMA"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes en formato de párrafo corrido, profesionales y concisos. IMPORTANTE: Mantén todas las tildes y acentos correctos en español."
                },
                {
                    "role": "user",
                    "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) sobre el siguiente contenido. No uses bullet points, no uses listas numeradas, no uses introducciones como 'A continuación' o 'El resumen es'. Ve directo al contenido. Mantén todas las tildes correctas:\n\n{transcription_text}"
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al generar resumen: {str(e)}"

def extract_quotes(segments):
    """Identifica citas textuales y declaraciones importantes"""
    quotes = []
    quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 
                      'indicó', 'comentó', 'aseguró', 'confirmó', 'negó', 'advirtió',
                      'explicó', 'destacó', 'subrayó', 'recalcó', 'sostuvo']
    
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        text_lower = text.lower()
        
        has_quotes = '"' in text or '«' in text or '»' in text
        has_declaration = any(keyword in text_lower for keyword in quote_keywords)
        
        if has_quotes or has_declaration:
            context_before = ""
            context_after = ""
            
            if i > 0:
                context_before = segments[i-1]['text'].strip()
            if i < len(segments) - 1:
                context_after = segments[i+1]['text'].strip()
            
            full_context = f"{context_before} {text} {context_after}".strip()
            
            quotes.append({
                'time': format_timestamp(seg['start']),
                'text': text,
                'full_context': full_context,
                'start': seg['start'],
                'type': 'quote' if has_quotes else 'declaration'
            })
    
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)
    return quotes[:10]

def export_to_srt(data):
    """Exporta a formato SRT (subtítulos)"""
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start = format_timestamp(seg['start']).replace(':', ',')
        end = format_timestamp(seg['end']).replace(':', ',')
        text = seg['text'].strip()
        srt_content.append(f"{i}\n{start},000 --> {end},000\n{text}\n")
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---

st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    model_option = st.selectbox(
        "Modelo de Transcripción",
        options=[
            "whisper-large-v3",
            "whisper-large-v3-turbo",
        ],
        index=0,
        help="Large-v3: Máxima precisión para español (RECOMENDADO) | Turbo: Más rápido"
    )
    
    language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0)
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="Mantén en 0.0 para máxima precisión")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    
    enable_summary = st.checkbox("📝 Generar resumen automático", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas y declaraciones", value=True)
    enable_tilde_fix = st.checkbox("✨ Corrección automática de tildes", value=True, 
                                    help="Repara palabras cortadas y corrige acentos")
    
    st.markdown("---")
    st.subheader("🔧 Procesamiento de Audio")
    
    if MOVIEPY_AVAILABLE:
        st.info("💡 Los archivos MP4 mayores a 25 MB se convertirán automáticamente")
        compress_audio_option = st.checkbox("📦 Comprimir audio adicional", value=False)
    else:
        st.warning("⚠️ MoviePy no disponible para conversión de video.")
        compress_audio_option = False
    
    st.markdown("---")
    st.info("💡 **Formatos:** MP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
    st.success("✅ API Key configurada correctamente")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader(
        "Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"],
        label_visibility="collapsed"
    )
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
                
                is_video = file_extension in ['.mp4', '.mpeg', '.mpga', '.webm']
                converted = False
                
                if is_video and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Archivo de {original_size:.2f} MB detectado. Convirtiendo..."):
                        file_bytes, converted = convert_video_to_audio(file_bytes, uploaded_file.name)
                        if converted:
                            new_size = get_file_size_mb(file_bytes)
                            reduction = ((original_size - new_size) / original_size) * 100
                            st.success(f"✅ Convertido: {original_size:.2f} MB → {new_size:.2f} MB (-{reduction:.1f}%)")
                
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo audio..."):
                        size_before = get_file_size_mb(file_bytes)
                        file_bytes = compress_audio(file_bytes, uploaded_file.name)
                        size_after = get_file_size_mb(file_bytes)
                        reduction = ((size_before - size_after) / size_before) * 100
                        st.success(f"✅ Audio comprimido: {size_before:.2f} MB → {size_after:.2f} MB (-{reduction:.1f}%)")
                
                st.session_state.uploaded_audio_bytes = file_bytes
                st.session_state.original_filename = uploaded_file.name
                
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_file_path = tmp.name
                
                with st.spinner("🔄 Transcribiendo con IA avanzada..."):
                    with open(tmp_file_path, "rb") as audio_file:
                        audio_content = audio_file.read()
                        safe_filename = uploaded_file.name.encode('utf-8').decode('utf-8')
                        
                        # PROMPT MEJORADO para forzar tildes en español
                        spanish_prompt = """Transcribe cuidadosamente en español con todos los acentos:
- Palabras con tilde obligatoria: qué, por qué, más, está, sí, sé, tú, mí, mí, él, ella
- Palabras terminadas en -ión: fundación, información, situación, declaración, nación, población
- Palabras terminadas en -ía: compañía, energía, geografía, economía, autonomía
- Nombres propios: Colombia, Amazonía, América
- Nunca cortes palabras en mitad de la sílaba. Completa todas las palabras."""
                        
                        transcription = client.audio.transcriptions.create(
                            file=(safe_filename, audio_content),
                            model=model_option,
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json",
                            prompt=spanish_prompt if language == "es" else None
                        )
                
                os.unlink(tmp_file_path)
                
                # Post-procesar para corregir tildes si está habilitado
                if enable_tilde_fix and language == "es":
                    with st.spinner("✨ Aplicando correcciones de tildes y palabras cortadas..."):
                        transcription_text = fix_spanish_encoding(transcription.text)
                        
                        # También corregir los segmentos individuales
                        if hasattr(transcription, 'segments'):
                            for segment in transcription.segments:
                                segment['text'] = fix_spanish_encoding(segment['text'])
                        
                        # Verificar calidad
                        quality_issues = check_transcription_quality(transcription_text)
                        if quality_issues:
                            for issue in quality_issues:
                                st.info(issue)
                else:
                    transcription_text = transcription.text
                
                st.session_state.transcription = transcription_text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary:
                        st.session_state.summary = generate_summary(transcription_text, client)
                    if enable_quotes:
                        st.session_state.quotes = extract_quotes(transcription.segments)
                
                st.success("✅ ¡Transcripción y análisis completados!")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Error durante la transcripción: {str(e)}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    
    # Reproductor de audio
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    st.write("")
    
    # PESTAÑAS PRINCIPALES
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "📊 Resumen", "💬 Citas y Declaraciones"])
    
    # ===== PESTAÑA 1: TRANSCRIPCIÓN =====
    with tab1:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        TRANSCRIPTION_BOX_STYLE = """
            background-color: #0E1117;
            color: #FAFAFA;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 1.5rem;
            max-height: 500px;
            overflow-y: auto;
            font-family: "Source Code Pro", "Consolas", monospace;
            line-height: 1.7;
            white-space: pre-wrap;
            font-size: 0.95rem;
        """

        # Búsqueda en transcripción
        col_search1, col_search2 = st.columns([4, 1])
        
        with col_search1:
            search_query = st.text_input(
                "🔎 Buscar en la transcripción:", 
                value=st.session_state.get('last_search', ''),
                placeholder="Escribe para encontrar y escuchar un momento exacto...",
                key=f"search_input_{st.session_state.get('search_counter', 0)}"
            )
            
            if search_query != st.session_state.get('last_search', ''):
                st.session_state.last_search = search_query
        
        with col_search2:
            st.write("")
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query):
                st.session_state.last_search = ""
                st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
                st.rerun()
        
        if search_query:
            with st.expander("Resultados de la búsqueda contextual", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]

                if not matching_indices:
                    st.info("No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)")
                    indices_to_display = set()
                    for idx in matching_indices:
                        indices_to_display.update(range(max(0, idx - 1), min(len(segments), idx + 2)))
                    
                    last_index = -2
                    for i in sorted(list(indices_to_display)):
                        if i > last_index + 1:
                            st.markdown("---")
                        
                        segment = segments[i]
                        start_seconds = int(segment['start'])
                        start_time_formatted = format_timestamp(start_seconds)
                        text = segment['text'].strip()

                        col_ts, col_text = st.columns([0.2, 0.8], gap="small")

                        with col_ts:
                            if st.button(f"▶️ {start_time_formatted}", key=f"play_search_{i}", use_container_width=True):
                                st.session_state.audio_start_time = start_seconds
                                st.rerun()

                        with col_text:
                            if i in matching_indices:
                                highlighted_text = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', text)
                                st.markdown(highlighted_text, unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='color: #888;'>{text}</span>", unsafe_allow_html=True)
                        last_index = i
        
        # Mostrar transcripción completa
        st.markdown("**Transcripción completa:**")
        
        if search_query:
            pattern = re.compile(re.escape(search_query), re.IGNORECASE)
            highlighted_transcription = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', st.session_state.transcription)
            transcription_html = highlighted_transcription.replace('\n', '<br>')
        else:
            transcription_html = st.session_state.transcription.replace('\n', '<br>')
            
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{transcription_html}</div>', unsafe_allow_html=True)

        # Botones de descarga
        st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1:
            transcription_utf8 = st.session_state.transcription.encode('utf-8').decode('utf-8')
            st.download_button(
                "💾 Descargar TXT Simple", 
                transcription_utf8.encode('utf-8'),
                "transcripcion.txt", 
                "text/plain; charset=utf-8",
                use_container_width=True
            )
        with col_d2:
            timestamped_text = format_transcription_with_timestamps(st.session_state.transcription_data)
            st.download_button(
                "💾 TXT con Tiempos", 
                timestamped_text.encode('utf-8'),
                "transcripcion_tiempos.txt", 
                "text/plain; charset=utf-8",
                use_container_width=True
            )
        with col_d3:
            srt_content = export_to_srt(st.session_state.transcription_data)
            st.download_button(
                "💾 SRT Subtítulos", 
                srt_content.encode('utf-8'),
                "subtitulos.srt", 
                "text/plain; charset=utf-8",
                use_container_width=True
            )
        with col_d4:
            create_copy_button(st.session_state.transcription)
    
    # ===== PESTAÑA 2: RESUMEN =====
    with tab2:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            
            st.write("")
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                st.download_button(
                    "💾 Descargar Resumen",
                    st.session_state.summary.encode('utf-8'),
                    "resumen.txt",
                    "text/plain; charset=utf-8",
                    use_container_width=True
                )
            with col_s2:
                create_copy_button(st.session_state.summary)
        else:
            st.info("📝 El resumen no fue generado. Activa la opción en el sidebar y vuelve a transcribir.")
    
    # ===== PESTAÑA 3: CITAS Y DECLARACIONES =====
    with tab3:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones Relevantes")
            st.caption(f"Se encontraron {len(st.session_state.quotes)} citas y declaraciones importantes")
            
            for idx, quote in enumerate(st.session_state.quotes):
                with st.container():
                    if quote['type'] == 'quote':
                        type_badge = "🗣️ **Cita Textual**"
                    else:
                        type_badge = "📢 **Declaración**"
                    
                    st.markdown(type_badge)
                    
                    col_q1, col_q2 = st.columns([0.12, 0.88])
                    with col_q1:
                        if st.button(f"▶️ {quote['time']}", key=f"quote_{idx}"):
                            st.session_state.audio_start_time = int(quote['start'])
                            st.rerun()
                    with col_q2:
                        st.markdown(f"*{quote['text']}*")
                        
                        if quote['full_context'] and quote['full_context'] != quote['text']:
                            with st.expander("📄 Ver contexto completo"):
                                st.markdown(quote['full_context'])
                    
                    st.markdown("---")
        else:
            st.info("💬 No se identificaron citas o declaraciones relevantes. Asegúrate de activar la opción en el sidebar.")
    
    # Botón de limpiar
    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo", type="secondary", use_container_width=False):
        keys_to_delete = ["transcription", "transcription_data", "uploaded_audio_bytes", "audio_start_time",
                        "summary", "quotes", "last_search", "search_counter", "original_filename"]
        for key in keys_to_delete:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'>
<p><strong>Transcriptor Pro - Johnascriptor - v2.2</strong> - Desarrollado por Johnathan Cortés 🤖</p>
<p style='font-size: 0.85rem;'>✨ Con reparación avanzada de palabras cortadas y acentos en español</p>
</div>""", unsafe_allow_html=True)
