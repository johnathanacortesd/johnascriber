import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta

# --- LÓGICA DE AUTENTICACIÓN ---

def check_password():
    """Devuelve True si la contraseña es correcta, de lo contrario False."""
    def password_entered():
        if st.session_state.get("password") == st.secrets.get("PASSWORD"):
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("Contraseña", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Contraseña incorrecta. Inténtalo de nuevo.")
    return False

# --- FUNCIONES AUXILIARES ---

# ***** INICIO DE LA SECCIÓN CORREGIDA *****
def create_copy_button(text_to_copy):
    """
    Crea un botón de "Copiar Todo" que utiliza un método robusto y compatible
    con todos los navegadores para copiar texto al portapapeles.
    """
    # Usamos json.dumps para escapar el texto de forma segura para JavaScript.
    text_json = json.dumps(text_to_copy)
    
    # Creamos un ID único para el botón para evitar conflictos.
    button_id = f"copy-button-{hash(text_to_copy)}"

    button_html = f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">
        📋 Copiar Todo
    </button>

    <script>
    document.getElementById("{button_id}").onclick = function() {{
        // Crear un elemento de área de texto temporal.
        const textArea = document.createElement("textarea");
        textArea.value = {text_json};

        // Hacer el área de texto invisible y añadirla al DOM.
        textArea.style.position = "fixed";
        textArea.style.top = "-9999px";
        textArea.style.left = "-9999px";
        document.body.appendChild(textArea);

        // Seleccionar el texto y ejecutar el comando de copiado.
        textArea.select();
        document.execCommand("copy");

        // Eliminar el área de texto temporal.
        document.body.removeChild(textArea);

        // Dar feedback visual al usuario.
        const button = document.getElementById("{button_id}");
        const originalText = button.innerText;
        button.innerText = "✅ ¡Copiado!";
        
        setTimeout(function() {{
            button.innerText = originalText;
        }}, 2000);
    }};
    </script>
    """
    components.html(button_html, height=40)
# ***** FIN DE LA SECCIÓN CORREGIDA *****

def format_timestamp(seconds):
    """Convierte segundos a un formato de tiempo HH:MM:SS."""
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

# --- INICIO DE LA APP ---

if check_password():
    st.set_page_config(page_title="Transcriptor de Audio", page_icon="🎙️", layout="wide")

    try:
        api_key = st.secrets["GROQ_API_KEY"]
    except KeyError:
        st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
        st.info("Por favor configura tu API Key en Settings → Secrets")
        st.stop()

    st.title("🎙️ Transcriptor de Audio con Groq")
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.header("⚙️ Configuración")
        st.subheader("Opciones de Transcripción")
        language = st.selectbox("Idioma", options=["es", "en", "fr", "de", "it", "pt", "ja", "ko", "zh"], index=0)
        temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0 = más preciso, 1 = más creativo")
        st.markdown("---")
        st.info("💡 **Formatos soportados:**\nMP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
        st.markdown("---")
        st.success("✅ API Key configurada correctamente")

    # --- SECCIÓN DE CARGA Y TRANSCRIPCIÓN ---
    st.subheader("1. Sube tu archivo y presiona Transcribir")
    col1, col2 = st.columns([3, 1])
    with col1:
        uploaded_file = st.file_uploader(
            "Selecciona un archivo de audio o video",
            type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"],
            label_visibility="collapsed"
        )
    with col2:
        if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
            with st.spinner("🔄 Transcribiendo..."):
                try:
                    client = Groq(api_key=api_key)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_file_path = tmp.name
                    with open(tmp_file_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model="whisper-large-v3",
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json"
                        )
                    os.unlink(tmp_file_path)
                    st.session_state.transcription = transcription.text
                    st.session_state.transcription_data = transcription
                    st.success("✅ ¡Transcripción completada!")
                except Exception as e:
                    st.error(f"❌ Error durante la transcripción: {str(e)}")

    # --- SECCIÓN DE RESULTADOS ---
    if 'transcription' in st.session_state:
        st.markdown("---")
        st.subheader("2. Revisa, Busca y Descarga")

        search_query = st.text_input("🔎 Buscar en la transcripción:", placeholder="Escribe una o más palabras...")
        
        if search_query:
            with st.expander("Resultados de la búsqueda contextual", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                
                matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]

                if not matching_indices:
                    st.info("No se encontraron coincidencias.")
                else:
                    indices_to_display = set()
                    for idx in matching_indices:
                        indices_to_display.add(idx)
                        if idx > 0:
                            indices_to_display.add(idx - 1)
                        if idx < len(segments) - 1:
                            indices_to_display.add(idx + 1)
                    
                    last_index = -2
                    for i in sorted(list(indices_to_display)):
                        if i > last_index + 1:
                            st.markdown("---")

                        segment = segments[i]
                        start_time = format_timestamp(segment['start'])
                        text = segment['text'].strip()

                        if i in matching_indices:
                            highlighted_text = pattern.sub(r'<mark>\g<0></mark>', text)
                            st.markdown(f"**[{start_time}]** → {highlighted_text}", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<span style='color: #666;'>[{start_time}] → {text}</span>", unsafe_allow_html=True)
                        
                        last_index = i

        st.text_area(
            "Transcripción completa:",
            value=st.session_state.transcription,
            height=400
        )
        
        st.write("") # Espacio
        b_col1, b_col2, b_col3, b_col4 = st.columns([1.5, 2, 1.2, 1])
        with b_col1:
            st.download_button("💾 Descargar TXT", st.session_state.transcription, "transcripcion.txt", "text/plain", use_container_width=True)
        with b_col2:
            timestamped_text = format_transcription_with_timestamps(st.session_state.transcription_data)
            st.download_button("💾 Descargar TXT (con tiempos)", timestamped_text, "transcripcion_con_tiempos.txt", "text/plain", use_container_width=True)
        with b_col3:
            create_copy_button(st.session_state.transcription)
        with b_col4:
            if st.button("🗑️ Limpiar", use_container_width=True):
                del st.session_state.transcription
                del st.session_state.transcription_data
                st.rerun()

    # --- FOOTER ---
    st.markdown("---")
    st.markdown("""<div style='text-align: center; color: #666;'><p>Desarrollado por Johnathan Cortés 🤖 usando Streamlit y API Key de Groq</p><p>🔗 <a href='https://console.groq.com' target='_blank'>Groq</a></p></div>""", unsafe_allow_html=True)
