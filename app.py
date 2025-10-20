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
            del st.session_state.password
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    # Pantalla de login mejorada
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
        
        # Solo mostrar error si ya intentó y falló (no al inicio)
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

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN ---

def convert_video_to_audio(video_bytes, video_filename):
    """Convierte video (MP4) a audio (MP3) con compresión"""
    try:
        # Guardar video temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp_video:
            tmp_video.write(video_bytes)
            video_path = tmp_video.name
        
        # Crear archivo de salida temporal
        audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
        
        # Extraer audio del video
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(
            audio_path,
            codec='mp3',
            bitrate='192k',  # Mejora: bitrate más alto para mejor calidad
            verbose=False,
            logger=None
        )
        video.close()
        
        # Leer el audio generado
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        
        # Limpiar archivos temporales
        os.unlink(video_path)
        os.unlink(audio_path)
        
        return audio_bytes, True
    except Exception as e:
        # Si falla, devolver el video original
        return video_bytes, False

def compress_audio(audio_bytes, original_filename):
    """Comprime audio reduciendo bitrate"""
    try:
        # Guardar audio temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes)
            audio_path = tmp_audio.name
        
        # Crear archivo comprimido
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        
        # Comprimir
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(
            compressed_path,
            codec='mp3',
            bitrate='128k',  # Mejora: bitrate más alto para mejor calidad
            verbose=False,
            logger=None
        )
        audio.close()
        
        # Leer el audio comprimido
        with open(compressed_path, 'rb') as f:
            compressed_bytes = f.read()
        
        # Limpiar archivos temporales
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
                    "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes en formato de párrafo corrido, profesionales y concisos."
                },
                {
                    "role": "user",
                    "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) sobre el siguiente contenido. No uses bullet points, no uses listas numeradas, no uses introducciones como 'A continuación' o 'El resumen es'. Ve directo al contenido:\n\n{transcription_text}"
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
    """Identifica citas textuales y declaraciones importantes con contexto mejorado"""
    quotes = []
    quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 
                      'indicó', 'comentó', 'aseguró', 'confirmó', 'negó', 'advirtió',
                      'explicó', 'destacó', 'subrayó', 'recalcó', 'sostuvo']
    
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        text_lower = text.lower()
        
        # Buscar comillas directas
        has_quotes = '"' in text or '«' in text or '»' in text
        
        # Buscar palabras clave de declaración
        has_declaration = any(keyword in text_lower for keyword in quote_keywords)
        
        if has_quotes or has_declaration:
            # Intentar obtener contexto adicional
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
    
    # Limitar a las 10 más relevantes (priorizar las que tienen comillas)
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

def correct_transcription(transcription_text, client):
    """Corrige la transcripción usando LLM para agregar tildes y corregir cortes"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Eres un corrector ortográfico experto en español de noticias. Corrige tildes, acentos y palabras cortadas (ej. 'qu' a 'qué', 'por qu' a 'por qué', 'Fundaci' a 'Fundación'). Une segmentos incompletos, mantén el significado original y asegura fluidez en contextos de documentales, noticias y entretenimiento sostenible."
                },
                {
                    "role": "user",
                    "content": f"Corrige la ortografía en español, agrega tildes donde falten, une palabras cortadas y mejora la coherencia: {transcription_text}"
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.0,
            max_tokens=2048  # Aumentado para manejar transcripciones más largas
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return transcription_text  # Si falla, devuelve original

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    model_option = st.selectbox(
        "Modelo de Transcripción",
        options=[
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "distil-whisper-large-v3-en"
        ],
        index=0,
        help="Large-v3: Máxima precisión (recomendado para español) | Turbo: Más rápido | Distil: Inglés optimizado"
    )
    
    language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0)
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0 = más preciso, 1 = más creativo")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    
    enable_summary = st.checkbox("📝 Generar resumen automático", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas y declaraciones", value=True)
    enable_correction = st.checkbox("🛠️ Corregir transcripción con IA (para tildes y cortes)", value=True)
    
    st.markdown("---")
    st.subheader("🔧 Procesamiento de Audio")
    
    if MOVIEPY_AVAILABLE:
        st.info("💡 Los archivos MP4 mayores a 25 MB se convertirán automáticamente a MP3")
        compress_audio_option = st.checkbox("📦 Comprimir audio adicional", value=False,
                                           help="Reduce más el tamaño (bitrate 128k). Solo para archivos muy grandes. Evítalo para máxima precisión.")
        avoid_high_compression = st.checkbox("🚫 Evitar compresión alta para precisión (recomendado para noticias)", value=True)
    else:
        st.warning("⚠️ MoviePy no disponible. Instala para conversión de video.")
        compress_audio_option = False
        avoid_high_compression = False
    
    st.markdown("---")
    st.info("💡 **Formatos soportados:** MP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
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
        # Limpiar búsqueda anterior y resetear tiempo de audio
        st.session_state.audio_start_time = 0
        st.session_state.last_search = ""
        st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
        
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                original_size = get_file_size_mb(file_bytes)
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                
                # Determinar si es video
                is_video = file_extension in ['.mp4', '.mpeg', '.mpga', '.webm']
                converted = False
                
                # Convertir SOLO si es video Y supera 25 MB
                if is_video and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Archivo de {original_size:.2f} MB detectado. Convirtiendo a MP3..."):
                        file_bytes, converted = convert_video_to_audio(file_bytes, uploaded_file.name)
                        if converted:
                            new_size = get_file_size_mb(file_bytes)
                            reduction = ((original_size - new_size) / original_size) * 100
                            st.success(f"✅ Convertido a MP3: {original_size:.2f} MB → {new_size:.2f} MB (-{reduction:.1f}%)")
                elif is_video and original_size > 25 and not MOVIEPY_AVAILABLE:
                    st.warning(f"⚠️ Archivo de {original_size:.2f} MB. MoviePy no disponible para conversión.")
                
                # Comprimir audio adicional si está habilitado y no se evita alta compresión
                if MOVIEPY_AVAILABLE and compress_audio_option and not avoid_high_compression:
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
                
                # Mejora: Verificar duración del audio
                if MOVIEPY_AVAILABLE:
                    audio_clip = AudioFileClip(tmp_file_path)
                    duration_minutes = audio_clip.duration / 60
                    audio_clip.close()
                    if duration_minutes > 60:
                        st.warning(f"⚠️ Audio largo ({duration_minutes:.1f} min). Posible truncado; considera dividir el archivo.")
                
                with st.spinner("🔄 Transcribiendo con IA avanzada..."):
                    with open(tmp_file_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model=model_option,
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json",
                            prompt="Transcripción precisa de noticias y documentales en español. Incluye tildes y acentos correctamente en palabras como qué, por qué, Fundación, Amazonía, lanzó, septiembre. Evita cortar palabras con tildes: política, economía, México, España, América Latina, documental, sostenible."  # Mejora: Prompt más específico para tildes y cortes comunes
                        )
                
                os.unlink(tmp_file_path)
                
                # Mejora: Reconstruir texto completo de segmentos para evitar truncados
                full_text = " ".join([seg['text'].strip() for seg in transcription.segments])
                
                # Mejora: Fuerza UTF-8 para tildes
                full_text = full_text.encode('utf-8').decode('utf-8')
                
                # Mejora: Corrección opcional con LLM, con prompt mejorado
                if enable_correction:
                    with st.spinner("🛠️ Corrigiendo transcripción con IA..."):
                        full_text = correct_transcription(full_text, client)
                
                st.session_state.transcription = full_text
                st.session_state.transcription_data = transcription
                
                # Debug: Mostrar info de transcripción
                st.write(f"Debug: {len(transcription.segments)} segmentos detectados. Texto total: {len(full_text)} chars.")
                
                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary:
                        st.session_state.summary = generate_summary(full_text, client)
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
    
    # PESTAÑAS PRINCIPALES: Transcripción | Resumen | Citas y Declaraciones
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "📊 Resumen", "💬 Citas y Declaraciones"])
    
    # ===== PESTAÑA 1: TRANSCRIPCIÓN =====
    with tab1:
        # --- Estilos para una mejor legibilidad ---
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
        # --- Fin de los estilos ---

        # Búsqueda en transcripción con botón de limpiar
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
            st.write("")  # Espaciado para alinear
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query):
                st.session_state.last_search = ""
                st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
                st.rerun()
        
        if search_query:
            with st.expander("Resultados de la búsqueda contextual", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE | re.UNICODE)  # Mejora: re.UNICODE para tildes
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
                        if i > last_index + 1: st.markdown("---")
                        
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
                                # Contexto con color más sutil pero legible
                                st.markdown(f"<span style='color: #888;'>{text}</span>", unsafe_allow_html=True)
                        last_index = i
        
        # Mostrar transcripción completa con un diseño mejorado
        st.markdown("**Transcripción completa:**")
        
        # Preparar el contenido HTML
        if search_query:
            pattern = re.compile(re.escape(search_query), re.IGNORECASE | re.UNICODE)  # Mejora: re.UNICODE
            # Aplicar resaltado
            highlighted_transcription = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', st.session_state.transcription)
            transcription_html = highlighted_transcription.replace('\n', '<br>')
        else:
            # Sin búsqueda, solo preparar para HTML
            transcription_html = st.session_state.transcription.replace('\n', '<br>')
            
        # Renderizar el contenedor estilizado
        st.markdown(f'<div style="{TRANSCRIPTION_BOX_STYLE}">{transcription_html}</div>', unsafe_allow_html=True)

        # Botones de descarga para transcripción
        st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1:
            st.download_button("💾 Descargar TXT Simple", st.session_state.transcription, "transcripcion.txt", "text/plain", use_container_width=True)
        with col_d2:
            timestamped_text = format_transcription_with_timestamps(st.session_state.transcription_data)
            st.download_button("💾 TXT con Tiempos", timestamped_text, "transcripcion_tiempos.txt", "text/plain", use_container_width=True)
        with col_d3:
            srt_content = export_to_srt(st.session_state.transcription_data)
            st.download_button("💾 SRT Subtítulos", srt_content, "subtitulos.srt", "text/plain", use_container_width=True)
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
                    st.session_state.summary,
                    "resumen.txt",
                    "text/plain",
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
                    # Indicador de tipo
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
                        
                        # Mostrar contexto expandible si está disponible
                        if quote['full_context'] and quote['full_context'] != quote['text']:
                            with st.expander("📄 Ver contexto completo"):
                                st.markdown(quote['full_context'])
                    
                    st.markdown("---")
        else:
            st.info("💬 No se identificaron citas o declaraciones relevantes. Asegúrate de activar la opción en el sidebar.")
    
    # Botón de limpiar (fuera de las pestañas)
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
<p><strong>Transcriptor Pro - Johnascriptor - v2.1</strong> - Desarrollado por Johnathan Cortés 🤖</p>
</div>""", unsafe_allow_html=True)
