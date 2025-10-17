import streamlit as st
from groq import Groq
import tempfile
import os
import hashlib

# Configuración de la página
st.set_page_config(
    page_title="Transcriptor de Audio",
    page_icon="🎙️",
    layout="wide"
)

# Obtener configuración desde secrets
try:
    api_key = st.secrets["GROQ_API_KEY"]
    access_password = st.secrets["ACCESS_PASSWORD"]
except:
    st.error("❌ Error: No se encontró la configuración en los secrets de Streamlit")
    st.info("Por favor configura GROQ_API_KEY y ACCESS_PASSWORD en Settings → Secrets")
    st.stop()

# Función para hashear contraseña
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Sistema de autenticación
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Acceso al Transcriptor de Audio")
    st.markdown("Por favor ingresa la contraseña para acceder a la aplicación")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        password_input = st.text_input(
            "Contraseña de acceso",
            type="password",
            key="password_input"
        )
        
        if st.button("Iniciar Sesión", type="primary", use_container_width=True):
            if hash_password(password_input) == access_password:
                st.session_state.authenticated = True
                st.success("✅ Acceso concedido")
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
        
        st.markdown("---")
        st.info("💡 Si no tienes acceso, contacta al administrador")
    
    st.stop()

# Si está autenticado, mostrar la aplicación
st.title("🎙️ Transcriptor de Audio con Groq")
st.markdown("Sube tu archivo de audio o video y obtén la transcripción en segundos")

# Botón de cerrar sesión en el sidebar
with st.sidebar:
    st.header("👤 Sesión")
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        if 'transcription' in st.session_state:
            del st.session_state.transcription
        if 'transcription_data' in st.session_state:
            del st.session_state.transcription_data
        st.rerun()
    
    st.markdown("---")
    st.header("⚙️ Configuración")
    
    # Configuraciones de transcripción
    st.subheader("Opciones de Transcripción")
    
    language = st.selectbox(
        "Idioma",
        options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"],
        index=0,
        help="Idioma del audio"
    )
    
    temperature = st.slider(
        "Temperatura",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.1,
        help="0 = más preciso, 1 = más creativo"
    )
    
    st.markdown("---")
    st.info("💡 **Formatos soportados:**\nMP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
    
    st.markdown("---")
    st.success("✅ API Key configurada")

# Área principal
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📁 Subir Archivo")
    
    uploaded_file = st.file_uploader(
        "Selecciona un archivo de audio o video",
        type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"],
        help="Tamaño máximo: 25 MB"
    )
    
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
                    # Crear cliente de Groq con la API key desde secrets
                    client = Groq(api_key=api_key)
                    
                    # Guardar archivo temporalmente
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_file_path = tmp_file.name
                    
                    # Realizar transcripción
                    with open(tmp_file_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model="whisper-large-v3",
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json",
                        )
                    
                    # Limpiar archivo temporal
                    os.unlink(tmp_file_path)
                    
                    # Guardar en session state
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
    
    # Área de texto con la transcripción
    transcription_text = st.text_area(
        "Transcripción:",
        value=st.session_state.transcription,
        height=300,
        help="Puedes copiar el texto directamente desde aquí"
    )
    
    # Botones de acción
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        st.download_button(
            label="💾 Descargar TXT",
            data=st.session_state.transcription,
            file_name="transcripcion.txt",
            mime="text/plain",
            use_container_width=True
        )
    
    with col2:
        if st.button("🗑️ Limpiar", use_container_width=True):
            del st.session_state.transcription
            del st.session_state.transcription_data
            st.rerun()
    
    # Estadísticas
    st.markdown("---")
    st.subheader("📊 Estadísticas")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        word_count = len(st.session_state.transcription.split())
        st.metric("Palabras", word_count)
    
    with col2:
        char_count = len(st.session_state.transcription)
        st.metric("Caracteres", char_count)
    
    with col3:
        if hasattr(st.session_state.transcription_data, 'duration'):
            duration = st.session_state.transcription_data.duration
            st.metric("Duración", f"{duration:.1f}s")
        else:
            st.metric("Idioma", language.upper())

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666;'>
        <p>Desarrollado con ❤️ usando Streamlit y Groq</p>
        <p>🔒 Aplicación protegida con autenticación</p>
    </div>
    """,
    unsafe_allow_html=True
)
