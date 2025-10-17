import streamlit as st
from groq import Groq
import tempfile
import os
import json
import streamlit.components.v1 as components
from datetime import timedelta

# --- LÓGICA DE AUTENTICACIÓN ---

def check_password():
    """Devuelve True si la contraseña es correcta, de lo contrario False."""
    def password_entered():
        """Verifica si la contraseña ingresada coincide con la de los secrets."""
        if st.session_state["password"] == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # No almacenar la contraseña en session_state
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Contraseña", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Contraseña", type="password", on_change=password_entered, key="password")
        st.error("😕 Contraseña incorrecta. Inténtalo de nuevo.")
        return False
    else:
        return True

# --- FUNCIONES AUXILIARES ---

def create_copy_button(text_to_copy):
    """Genera un componente de Streamlit con un botón para copiar texto al portapapeles."""
    # Usamos json.dumps para escapar correctamente el texto para JavaScript
    text_json = json.dumps(text_to_copy)
    
    button_html = f"""
    <button id="copyBtn" onclick="copyToClipboard(this, {text_json})" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">
        📋 Copiar Todo
    </button>
    <script>
    function copyToClipboard(element, text) {{
        navigator.clipboard.writeText(text).then(function() {{
            element.innerText = "✅ ¡Copiado!";
            setTimeout(function() {{
                element.innerText = "📋 Copiar Todo";
            }}, 2000);
        }}, function(err) {{
            console.error('Error al copiar: ', err);
        }});
    }}
    </script>
    """
    components.html(button_html, height=40)

def format_timestamp(seconds):
    """Convierte segundos a un formato de tiempo HH:MM:SS,ms."""
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = delta.microseconds // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def format_transcription_with_timestamps(data):
    """Formatea la transcripción con marcas de tiempo a partir de la respuesta verbose_json."""
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    
    lines = []
    for segment in data.segments:
        start_time = format_timestamp(segment['start'])
        end_time = format_timestamp(segment['end'])
        text = segment['text']
        lines.append(f"[{start_time} --> {end_time}] {text.strip()}")
        
    return "\n".join(lines)


# --- INICIO DE LA APP ---

if check_password():

    # Configuración de la página
    st.set_page_config(
        page_title="Transcriptor de Audio",
        page_icon="🎙️",
        layout="wide"
    )

    # Obtener API Key desde secrets
    try:
        api_key = st.secrets["GROQ_API_KEY"]
    except KeyError:
        st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
        st.info("Por favor configura tu API Key en Settings → Secrets")
        st.stop()

    # Título
    st.title("🎙️ Transcriptor de Audio con Groq")
    st.markdown("Sube tu archivo de audio o video y obtén la transcripción en segundos")

    # Sidebar para configuraciones
    with st.sidebar:
        st.header("⚙️ Configuración")
        st.subheader("Opciones de Transcripción")
        language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0, help="Idioma del audio")
        temperature = st.slider("Temperatura", min_value=0.0, max_value=1.0, value=0.0, step=0.1, help="0 = más preciso, 1 = más creativo")
        st.markdown("---")
        st.info("💡 **Formatos soportados:**\nMP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
        st.markdown("---")
        st.success("✅ API Key configurada correctamente")

    # Área principal
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📁 Subir Archivo")
        uploaded_file = st.file_uploader("Selecciona un archivo de audio o video", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], help="Tamaño máximo: 25 MB")
        if uploaded_file:
            st.success(f"✅ Archivo cargado: {uploaded_file.name}")
            st.write(f"**Tamaño:** {uploaded_file.size / 1024 / 1024:.2f} MB")

    with col2:
        st.subheader("🚀 Transcribir")
        if st.button("Iniciar Transcripción", type="primary", use_container_width=True):
            if not uploaded_file:
                st.error("❌ Por favor sube un archivo de audio")
            else:
                try:
                    with st.spinner("🔄 Transcribiendo... Esto puede tomar unos momentos"):
                        client = Groq(api_key=api_key)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                            tmp_file.write(uploaded_file.getvalue())
                            tmp_file_path = tmp_file.name
                        
                        with open(tmp_file_path, "rb") as audio_file:
                            transcription = client.audio.transcriptions.create(
                                file=(uploaded_file.name, audio_file.read()),
                                model="whisper-large-v3",
                                temperature=temperature,
                                language=language,
                                response_format="verbose_json",
                            )
                        
                        os.unlink(tmp_file_path)
                        st.session_state.transcription = transcription.text
                        st.session_state.transcription_data = transcription
                        st.success("✅ ¡Transcripción completada!")
                        
                except Exception as e:
                    st.error(f"❌ Error durante la transcripción: {str(e)}")
                    if "authentication" in str(e).lower():
                        st.warning("Verifica que tu API Key en Secrets sea correcta")

    # Mostrar resultado
    if hasattr(st.session_state, 'transcription'):
        st.markdown("---")
        st.subheader("📝 Resultado de la Transcripción")
        
        transcription_text = st.text_area("Transcripción:", value=st.session_state.transcription, height=300, help="Puedes copiar el texto directamente desde aquí")
        
        # Botones de acción
        col1, col2, col3, col4 = st.columns([1.5, 1.8, 1.2, 1])
        
        with col1:
            st.download_button(label="💾 Descargar TXT", data=st.session_state.transcription, file_name="transcripcion.txt", mime="text/plain", use_container_width=True)
        
        with col2:
            timestamped_text = format_transcription_with_timestamps(st.session_state.transcription_data)
            st.download_button(label="💾 Descargar TXT (con tiempos)", data=timestamped_text, file_name="transcripcion_con_tiempos.txt", mime="text/plain", use_container_width=True)

        with col3:
             create_copy_button(transcription_text)

        with col4:
            if st.button("🗑️ Limpiar", use_container_width=True):
                del st.session_state.transcription
                del st.session_state.transcription_data
                st.rerun()
        
        # Estadísticas
        st.markdown("---")
        st.subheader("📊 Estadísticas")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Palabras", len(st.session_state.transcription.split()))
        with col2:
            st.metric("Caracteres", len(st.session_state.transcription))
        with col3:
            if hasattr(st.session_state.transcription_data, 'duration'):
                st.metric("Duración", f"{st.session_state.transcription_data.duration:.1f}s")
            else:
                st.metric("Idioma", language.upper())

    # Footer
    st.markdown("---")
    st.markdown("""<div style='text-align: center; color: #666;'><p>Desarrollado por Johnathan Cortés 🤖 usando Streamlit y Groq</p><p>🔗 <a href='https://console.groq.com' target='_blank'>Obtén tu API Key en Groq</a></p></div>""", unsafe_allow_html=True)
