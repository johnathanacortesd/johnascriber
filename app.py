import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter

# --- LÓGICA DE AUTENTICACIÓN ROBUSTA ---

if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        if "password" in st.session_state:
            del st.session_state.password
    else:
        st.session_state.password_correct = False

if not st.session_state.password_correct:
    st.title("Acceso Protegido")
    st.markdown("Por favor, introduce la contraseña para usar el transcriptor.")
    st.text_input("Contraseña", type="password", on_change=validate_password, key="password")
    if "password" in st.session_state and not st.session_state.password_correct:
        st.error("😕 Contraseña incorrecta. Inténtalo de nuevo.")
    st.stop()

# --- INICIO DE LA APP PRINCIPAL ---

st.set_page_config(page_title="Transcriptor Pro", page_icon="🎙️", layout="wide")

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

# --- NUEVAS FUNCIONES AVANZADAS ---

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

def extract_key_topics(transcription_text):
    """Extrae palabras clave y temas principales"""
    stop_words = {'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'ser', 'se', 'no', 'haber', 
                  'por', 'con', 'su', 'para', 'como', 'estar', 'tener', 'le', 'lo', 'todo',
                  'pero', 'más', 'hacer', 'o', 'poder', 'decir', 'este', 'ir', 'otro', 'ese',
                  'es', 'son', 'al', 'del', 'una', 'los', 'las', 'unos', 'unas', 'ya', 'muy',
                  'sin', 'sobre', 'también', 'me', 'hasta', 'hay', 'donde', 'quien', 'desde',
                  'todos', 'durante', 'según', 'sin', 'entre', 'cuando', 'él', 'ella', 'sido'}
    
    words = re.findall(r'\b[a-záéíóúñ]{4,}\b', transcription_text.lower())
    filtered_words = [w for w in words if w not in stop_words]
    
    word_freq = Counter(filtered_words)
    return word_freq.most_common(10)

def extract_quotes(segments):
    """Identifica posibles citas textuales importantes"""
    quotes = []
    for seg in segments:
        text = seg['text'].strip()
        if '"' in text or 'dijo' in text.lower() or 'afirmó' in text.lower() or 'declaró' in text.lower():
            quotes.append({
                'time': format_timestamp(seg['start']),
                'text': text,
                'start': seg['start']
            })
    return quotes[:8]

def export_to_srt(data):
    """Exporta a formato SRT (subtítulos)"""
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start = format_timestamp(seg['start']).replace(':', ',')
        end = format_timestamp(seg['end']).replace(':', ',')
        text = seg['text'].strip()
        srt_content.append(f"{i}\n{start},000 --> {end},000\n{text}\n")
    return "\n".join(srt_content)

def detect_speakers(segments):
    """Detecta cambios de hablante por pausas prolongadas"""
    speakers = []
    current_speaker = 1
    silence_threshold = 2.0
    
    for i, seg in enumerate(segments):
        if i > 0:
            gap = seg['start'] - segments[i-1]['end']
            if gap > silence_threshold:
                current_speaker += 1
        
        speakers.append({
            'speaker': f'Hablante {current_speaker}',
            'time': format_timestamp(seg['start']),
            'text': seg['text'].strip(),
            'start': seg['start']
        })
    
    return speakers

def format_speaker_transcript(speakers):
    """Formatea transcripción con identificación de hablantes"""
    result = []
    current_speaker = None
    
    for item in speakers:
        if item['speaker'] != current_speaker:
            result.append(f"\n{item['speaker']} ({item['time']}):")
            current_speaker = item['speaker']
        result.append(f"{item['text']}")
    
    return "\n".join(result)

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Análisis Avanzado de Audio")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    model_option = st.selectbox(
        "Modelo de Transcripción",
        options=[
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "distil-whisper-large-v3-en"
        ],
        help="Large-v3: Máxima precisión | Turbo: Más rápido | Distil: Inglés optimizado"
    )
    
    language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0)
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0 = más preciso, 1 = más creativo")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    
    enable_summary = st.checkbox("📝 Generar resumen automático", value=True)
    enable_topics = st.checkbox("🏷️ Extraer temas clave", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas", value=True)
    enable_speakers = st.checkbox("👥 Detectar hablantes", value=False, help="Identifica cambios de speaker")
    
    st.markdown("---")
    st.info("💡 **Formatos soportados:** MP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
    st.success("✅ API Key configurada correctamente")

st.subheader("1. Sube tu archivo y presiona Transcribir")
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
        if 'search_query' in st.session_state:
            del st.session_state.search_query
        
        with st.spinner("🔄 Transcribiendo con IA avanzada..."):
            try:
                st.session_state.uploaded_audio_bytes = uploaded_file.getvalue()
                
                client = Groq(api_key=api_key)
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
                    tmp.write(st.session_state.uploaded_audio_bytes)
                    tmp_file_path = tmp.name
                with open(tmp_file_path, "rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        file=(uploaded_file.name, audio_file.read()),
                        model=model_option,
                        temperature=temperature,
                        language=language,
                        response_format="verbose_json"
                    )
                os.unlink(tmp_file_path)
                st.session_state.transcription = transcription.text
                st.session_state.transcription_data = transcription
                
                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary:
                        st.session_state.summary = generate_summary(transcription.text, client)
                    if enable_topics:
                        st.session_state.topics = extract_key_topics(transcription.text)
                    if enable_quotes:
                        st.session_state.quotes = extract_quotes(transcription.segments)
                    if enable_speakers:
                        st.session_state.speakers = detect_speakers(transcription.segments)
                
                st.success("✅ ¡Transcripción y análisis completados!")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Error durante la transcripción: {str(e)}")

if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("2. Reproduce y Analiza")
    
    # Reproductor de audio
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    st.write("")
    
    # PESTAÑAS PRINCIPALES: Transcripción | Resumen | Análisis Avanzado
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "📊 Resumen", "🔬 Análisis Avanzado"])
    
    # ===== PESTAÑA 1: TRANSCRIPCIÓN =====
    with tab1:
        # Búsqueda en transcripción
        search_query = st.text_input(
            "🔎 Buscar en la transcripción:", 
            placeholder="Escribe para encontrar y escuchar un momento exacto...",
            key="search_query"
        )
        
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
                                highlighted_text = pattern.sub(r'<mark>\g<0></mark>', text)
                                st.markdown(highlighted_text, unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='color: #666;'>{text}</span>", unsafe_allow_html=True)
                        last_index = i
        
        st.text_area("Transcripción completa:", value=st.session_state.transcription, height=500)
        
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
    
    # ===== PESTAÑA 3: ANÁLISIS AVANZADO =====
    with tab3:
        # Sub-pestañas para análisis avanzado
        subtab1, subtab2, subtab3 = st.tabs(["🏷️ Temas Clave", "💬 Citas Destacadas", "👥 Hablantes"])
        
        with subtab1:
            if 'topics' in st.session_state:
                st.markdown("### 🏷️ Palabras y Temas Más Frecuentes")
                cols = st.columns(2)
                for idx, (word, count) in enumerate(st.session_state.topics):
                    with cols[idx % 2]:
                        st.metric(label=word.capitalize(), value=f"{count} menciones")
            else:
                st.info("🏷️ El análisis de temas no fue generado. Activa la opción en el sidebar.")
        
        with subtab2:
            if 'quotes' in st.session_state and st.session_state.quotes:
                st.markdown("### 💬 Citas y Declaraciones Relevantes")
                for idx, quote in enumerate(st.session_state.quotes):
                    with st.container():
                        col_q1, col_q2 = st.columns([0.15, 0.85])
                        with col_q1:
                            if st.button(f"▶️ {quote['time']}", key=f"quote_{idx}"):
                                st.session_state.audio_start_time = int(quote['start'])
                                st.rerun()
                        with col_q2:
                            st.markdown(f"💬 *{quote['text']}*")
                        st.markdown("---")
            else:
                st.info("💬 No se identificaron citas relevantes o la función está desactivada.")
        
        with subtab3:
            if 'speakers' in st.session_state:
                st.markdown("### 👥 Detección de Hablantes")
                current_speaker = None
                for item in st.session_state.speakers:
                    if item['speaker'] != current_speaker:
                        st.markdown(f"#### {item['speaker']}")
                        current_speaker = item['speaker']
                    
                    col_s1, col_s2 = st.columns([0.15, 0.85])
                    with col_s1:
                        if st.button(f"▶️ {item['time']}", key=f"speaker_{item['start']}"):
                            st.session_state.audio_start_time = int(item['start'])
                            st.rerun()
                    with col_s2:
                        st.markdown(f"{item['text']}")
                
                st.write("")
                st.download_button(
                    "💾 Descargar TXT con Hablantes",
                    format_speaker_transcript(st.session_state.speakers),
                    "transcripcion_speakers.txt",
                    "text/plain",
                    use_container_width=True
                )
            else:
                st.warning("👥 **La detección de hablantes está desactivada**")
                st.markdown("""
                Para activar esta función:
                1. Ve al **sidebar** (menú lateral izquierdo) ⬅️
                2. Busca la sección **"🎯 Análisis Inteligente"**
                3. Marca la casilla **"👥 Detectar hablantes"**
                4. Sube un nuevo audio y transcribe
                
                Esta función identifica automáticamente cambios de hablante basándose en pausas en el audio.
                """)
    
    # Botón de limpiar (fuera de las pestañas)
    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo", type="secondary", use_container_width=False):
        keys_to_delete = ["transcription", "transcription_data", "uploaded_audio_bytes", "audio_start_time",
                        "summary", "topics", "quotes", "speakers", "search_query"]
        for key in keys_to_delete:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'>
<p><strong>Transcriptor Pro v2.0</strong> - Desarrollado con ❤️ para análisis periodístico</p>
<p>🔗 <a href='https://console.groq.com' target='_blank'>Groq Console</a> | 
📚 <a href='https://console.groq.com/docs/models' target='_blank'>Modelos Disponibles</a></p>
</div>""", unsafe_allow_html=True)
