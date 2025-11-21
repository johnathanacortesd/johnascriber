import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta

# --- LÓGICA DE AUTENTICACIÓN ---
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
        <p style='color: #666; margin-bottom: 2rem;'>Versión Exacta V9 - Corrección de Tildes y Nombres</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro - V9 Exacta", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# --- CALLBACKS UI ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def clean_whisper_artifacts(text):
    """Limpieza suave. NO toca tildes ni caracteres unicode."""
    if not text:
        return text
    
    # Elimina repeticiones comunes de alucinaciones de Whisper
    patterns_to_remove = [
        r'(Palabras clave[.\s]*){2,}',
        r'(Subtítulos[.\s]*){2,}',
        r'(Música[.\s]*){3,}',
        r'(Gracias[.\s]*){3,}',
        r'(\[Música\][.\s]*){2,}',
    ]
    
    result = text
    for pattern in patterns_to_remove:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    # Reduce espacios y puntos excesivos sin borrar caracteres válidos
    result = re.sub(r'\s{3,}', ' ', result)
    result = re.sub(r'\.{3,}', '...', result)
    
    return result.strip()

# --- OPTIMIZACIÓN DE AUDIO (MEJORADA PARA CALIDAD) ---
def optimize_audio_robust(file_bytes, filename):
    file_ext = os.path.splitext(filename)[1]
    if not file_ext: file_ext = ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path + "_opt.mp3"
    original_size = len(file_bytes) / (1024 * 1024)
    
    try:
        # SUBIDA DE CALIDAD: 64k bitrate y 22050Hz para capturar mejor la 'T' vs 'V'
        command = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "22050", "-ac", "1", "-b:a", "64k",
            "-f", "mp3", output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, 'rb') as f:
                new_bytes = f.read()
            
            final_size = len(new_bytes) / (1024 * 1024)
            os.unlink(input_path); os.unlink(output_path)
            
            reduction = ((original_size - final_size) / original_size * 100) if original_size > 0 else 0
            return new_bytes, {'converted': True, 'message': f"✅ Optimizado (Alta Calidad): {original_size:.1f}MB → {final_size:.1f}MB (-{reduction:.0f}%)"}
        else:
            raise Exception("Falló conversión FFmpeg")

    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, {'converted': False, 'message': f"⚠️ Usando original. Error: {str(e)}"}

# --- FUNCIONES DE ANÁLISIS Y LLM ---
def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto. Crea un resumen ejecutivo en español."},
                {"role": "user", "content": f"Resume este contenido:\n\n{transcription_text[:15000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Contexto:\n{transcription_text[:25000]}\n\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def export_to_srt(data):
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start = timedelta(seconds=seg['start'])
        end = timedelta(seconds=seg['end'])
        s_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        e_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt_content.append(f"{i}\n{s_str} --> {e_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")
st.markdown("**Modo de Exactitud Activado**: Prioridad a nombres propios (Tigo, etc) y acentos.")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    st.info("💡 CONSEJO: Para evitar que confunda 'Tigo' con 'Vivo', escríbelo abajo.")
    
    # VOCABULARIO CRÍTICO
    vocab_input = st.text_area(
        "📖 Vocabulario / Palabras Clave:",
        value="Tigo, telefonía, prácticamente, comunicación, cliente, soporte",
        help="Escribe aquí los nombres propios o palabras difíciles separados por comas. Esto guía a Whisper para no inventar."
    )
    
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    
    st.divider()
    st.caption("Motor: Whisper Large V3 (Temperature 0.0 - Determinístico)")
    st.caption("Audio: MP3 Mono 64kbps (Alta fidelidad de voz)")

st.subheader("📤 Sube tu archivo (Audio/Video)")
uploaded_file = st.file_uploader("Selecciona archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mov", "avi"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción Exacta", type="primary", use_container_width=True, disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    try:
        # 1. OPTIMIZACIÓN
        with st.spinner("🔄 Optimizando audio (Calidad Voz HD)..."):
            file_bytes, conversion_info = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = file_bytes
            if conversion_info['converted']:
                st.success(conversion_info['message'])
            else:
                st.warning(conversion_info['message'])

        client = Groq(api_key=api_key)
        
        # 2. TRANSCRIPCIÓN CON WHISPER (Configuración Estricta)
        with st.spinner("🔄 Transcribiendo (Detectando Tigo, tildes y gramática)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # Construimos un prompt gramaticalmente correcto que incluye las palabras clave del usuario
            user_vocab = vocab_input.replace("\n", ", ").strip()
            whisper_system_prompt = f"La siguiente es una transcripción literal en español. Uso correcto de tildes y puntuación. Vocabulario específico incluye: {user_vocab}."
            
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_file.read()), 
                    model="whisper-large-v3", 
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0,  # CERO = Máxima determinismo, menos invención
                    prompt=whisper_system_prompt
                )
            os.unlink(tmp_path)
        
        # 3. LIMPIEZA SEGURA (Sin cortar tildes)
        # Usamos directamente el texto de Whisper porque V3 con temp=0 suele ser el más exacto gramaticalmente
        raw_text = transcription.text
        cleaned_text = clean_whisper_artifacts(raw_text)
        
        # NO aplicamos post-procesamiento LLM aquí por defecto para evitar que invente o cambie palabras.
        # Whisper V3 ya pone tildes muy bien si el prompt es bueno.
        
        st.session_state.transcription = cleaned_text
        st.session_state.transcription_data = transcription
        
        if enable_summary:
            with st.spinner("📝 Generando resumen..."):
                st.session_state.summary = generate_summary(cleaned_text, client)
        
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error crítico: {e}")
        import traceback
        st.code(traceback.format_exc())

# --- VISUALIZACIÓN ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproductor")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📝 Transcripción Exacta", "📊 Resumen y Chat"])
    
    # --- TAB 1: TRANSCRIPCIÓN ---
    with tab1:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        col1, col2 = st.columns([4, 1])
        search_query = col1.text_input("🔎 Buscar en texto:", key="search_input")
        col2.write(""); col2.button("🗑️", on_click=clear_search_callback)

        # BÚSQUEDA
        if search_query:
            full_text = st.session_state.transcription
            # Regex seguro para unicode
            try:
                pattern = re.compile(re.escape(search_query), re.IGNORECASE | re.UNICODE)
                matches = list(pattern.finditer(full_text))
                if matches:
                    st.markdown(f"**{len(matches)} coincidencia(s)**")
                    for idx, match in enumerate(matches):
                        start = max(0, match.start() - 100)
                        end = min(len(full_text), match.end() + 100)
                        context = full_text[start:end].replace("\n", " ")
                        
                        # Resaltado
                        context_html = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', context)
                        
                        st.markdown(f"""<div style="background:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px; color:black;">...{context_html}...</div>""", unsafe_allow_html=True)
                else:
                    st.warning("No se encontraron coincidencias.")
            except Exception as e:
                st.error(f"Error en búsqueda: {e}")

        st.markdown("### 📄 Texto Transcrito")
        st.text_area("Contenido", st.session_state.transcription, height=600, label_visibility="collapsed")
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2,2,2,1.5])
        c1.download_button("💾 Descargar TXT", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        c2.download_button("💾 Descargar Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "tiempos.txt", use_container_width=True)
        c3.download_button("💾 Descargar SRT", export_to_srt(st.session_state.transcription_data), "subs.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    # --- TAB 2: RESUMEN Y CHAT ---
    with tab2:
        if 'summary' in st.session_state:
            st.markdown(f"### 📝 Resumen Ejecutivo\n{st.session_state.summary}")
            st.divider()
            
            st.markdown("### 💬 Chat con el Audio")
            for qa in st.session_state.qa_history:
                st.markdown(f"**Q:** {qa['question']}")
                st.markdown(f"**A:** {qa['answer']}")
                st.divider()
            
            with st.form("chat_form"):
                q = st.text_area("Haz una pregunta sobre el contenido:")
                if st.form_submit_button("Preguntar") and q:
                    with st.spinner("Pensando..."):
                        ans = answer_question(q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                        st.session_state.qa_history.append({'question': q, 'answer': ans})
                        st.rerun()
        else: st.info("Resumen no generado.")

    if st.sidebar.button("🗑️ Limpiar Todo"):
        st.session_state.clear()
        st.rerun()
