import streamlit as st
from groq import Groq
import openai
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
        <h2>Transcriptor Pro - Johnascriptor V10</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Limpieza GPT-5 + Navegación por Tiempo</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro - V10 GPT-5", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    groq_api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# Intentar cargar OpenAI key de secrets si existe
openai_api_key_default = st.secrets.get("OPENAI_API_KEY", "")

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

def format_transcription_with_timestamps(segments):
    if not segments:
        return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in segments]
    return "\n".join(lines)

def clean_whisper_artifacts(text):
    """Limpieza básica de alucinaciones comunes de Whisper."""
    if not text: return text
    patterns = [
        r'(Palabras clave[.\s]*){2,}', r'(Subtítulos[.\s]*){2,}',
        r'(Música[.\s]*){3,}', r'(Gracias[.\s]*){3,}',
        r'(\[Música\][.\s]*){2,}'
    ]
    result = text
    for p in patterns: result = re.sub(p, '', result, flags=re.IGNORECASE)
    return result.strip()

# --- FUNCIONES DE AUDIO ---
def optimize_audio_robust(file_bytes, filename):
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path + "_opt.mp3"
    original_size = len(file_bytes) / (1024 * 1024)
    
    try:
        # 64k para mantener fidelidad en consonantes (T vs V)
        command = ["ffmpeg", "-y", "-i", input_path, "-vn", "-ar", "22050", "-ac", "1", "-b:a", "64k", "-f", "mp3", output_path]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, 'rb') as f: new_bytes = f.read()
            final_size = len(new_bytes) / (1024 * 1024)
            os.unlink(input_path); os.unlink(output_path)
            return new_bytes, {'converted': True, 'message': f"✅ Optimizado: {original_size:.1f}MB → {final_size:.1f}MB"}
        else: raise Exception("Falló conversión FFmpeg")
    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, {'converted': False, 'message': f"⚠️ Usando original. Error: {str(e)}"}

# --- CORRECCIÓN CON GPT-5 (SEGMENTO POR SEGMENTO) ---
def correct_segments_with_gpt5(segments, api_key, model_name):
    """
    Corrige el texto manteniendo la estructura de segmentos para no perder los timestamps.
    Agrupa segmentos para ser eficiente, corrige, y luego desglosa.
    """
    client = openai.OpenAI(api_key=api_key)
    corrected_segments = []
    
    # Agrupamos segmentos de 10 en 10 para no hacer mil llamadas a la API
    batch_size = 10
    
    progress_bar = st.progress(0, text="🧠 Aplicando corrección GPT-5...")
    
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        # Creamos un texto con separadores para que el modelo respete la estructura
        batch_text = "\n|||\n".join([s['text'] for s in batch])
        
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "Eres un corrector experto. Tu ÚNICA tarea es corregir tildes, puntuación y errores tipográficos (ej: 'telefon' -> 'telefonía', 'pr' -> 'prácticamente'). NO resumas. NO cambies el significado. NO elimines contenido. Devuelve el texto con los mismos separadores '|||'."},
                    {"role": "user", "content": batch_text}
                ],
                temperature=0.1 # Bajo para precisión
            )
            
            fixed_text_block = response.choices[0].message.content
            fixed_parts = fixed_text_block.split("|||")
            
            # Si el modelo devuelve la misma cantidad de partes, asignamos. Si no, usamos el original (fallback de seguridad)
            if len(fixed_parts) == len(batch):
                for j, seg in enumerate(batch):
                    new_seg = seg.copy()
                    new_seg['text'] = fixed_parts[j].strip()
                    corrected_segments.append(new_seg)
            else:
                # Fallback: si el modelo rompió la estructura, guardamos los originales de este lote
                corrected_segments.extend(batch)
                
        except Exception as e:
            st.warning(f"⚠️ Error conectando con GPT-5 en lote {i}: {e}")
            corrected_segments.extend(batch)
            
        progress_bar.progress(min((i + batch_size) / len(segments), 1.0))
    
    progress_bar.empty()
    return corrected_segments

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - V10")
st.markdown("Con motor de limpieza **gpt-5-nano-2025-08-07** y navegación temporal.")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    # SECCIÓN DE WHISPER (GROQ)
    st.subheader("1. Transcripción (Groq)")
    vocab_input = st.text_area("Vocabulario / Nombres:", value="Tigo, telefonía, prácticamente, cliente", height=70)
    
    st.markdown("---")
    
    # SECCIÓN DE LIMPIEZA (OPENAI / GPT-5)
    st.subheader("2. Limpieza Premium")
    use_gpt5 = st.checkbox("✅ Activar corrección GPT-5", value=True)
    
    openai_key = st.text_input("OpenAI API Key (Para GPT-5)", value=openai_api_key_default, type="password")
    model_cleanup = st.selectbox("Modelo de limpieza:", ["gpt-5-nano-2025-08-07", "gpt-4o", "gpt-3.5-turbo"], index=0)
    
    st.info("El modelo 'gpt-5-nano' debe estar disponible en tu cuenta de OpenAI.")

# --- SUBIDA Y PROCESO ---
uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "mpeg"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción + Limpieza", type="primary", use_container_width=True, disabled=not uploaded_file):
    if use_gpt5 and not openai_key:
        st.error("❌ Necesitas una API Key de OpenAI para usar el modelo GPT-5.")
        st.stop()
        
    st.session_state.qa_history = []
    
    try:
        # 1. OPTIMIZACIÓN
        with st.spinner("🔄 Optimizando audio..."):
            file_bytes, conversion_info = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = file_bytes
            if conversion_info['converted']: st.success(conversion_info['message'])
        
        # 2. TRANSCRIPCIÓN WHISPER (GROQ)
        client_groq = Groq(api_key=groq_api_key)
        with st.spinner("🔄 Transcribiendo (Whisper V3)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            user_vocab = vocab_input.replace("\n", ", ").strip()
            prompt_sys = f"Transcripción en español exacta. Vocabulario: {user_vocab}."
            
            with open(tmp_path, "rb") as af:
                transcription = client_groq.audio.transcriptions.create(
                    file=("audio.mp3", af.read()), 
                    model="whisper-large-v3", 
                    language="es", 
                    response_format="verbose_json", 
                    temperature=0.0, 
                    prompt=prompt_sys
                )
            os.unlink(tmp_path)
        
        # Preparamos los segmentos crudos
        raw_segments = transcription.segments
        
        # 3. CORRECCIÓN GPT-5 (Si está activo)
        if use_gpt5:
            final_segments = correct_segments_with_gpt5(raw_segments, openai_key, model_cleanup)
            st.success(f"✨ Texto corregido con {model_cleanup}")
        else:
            final_segments = raw_segments
        
        # Reconstruir texto completo a partir de segmentos (corregidos o no)
        full_text = " ".join([s['text'] for s in final_segments])
        
        # Guardar en sesión
        st.session_state.segments = final_segments
        st.session_state.transcription = full_text
        
        # Generar resumen con el texto final
        with st.spinner("📝 Generando resumen..."):
            try:
                # Usamos Groq/Llama para el resumen para ahorrar tokens de OpenAI
                res_comp = client_groq.chat.completions.create(
                    messages=[{"role": "user", "content": f"Resume esto:\n{full_text[:10000]}"}],
                    model="llama-3.1-8b-instant"
                )
                st.session_state.summary = res_comp.choices[0].message.content
            except: st.session_state.summary = "No se pudo generar resumen."

        st.rerun()

    except Exception as e:
        st.error(f"❌ Error: {e}")

# --- VISUALIZACIÓN (CON TIMESTAMPS INTERACTIVOS) ---
if 'segments' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproductor y Texto Interactivo")
    
    # Reproductor de audio que obedece a st.session_state.audio_start_time
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción Interactiva", "📄 Texto Plano", "📊 Resumen"])
    
    # TAB 1: INTERACTIVO (LO QUE PEDISTE RECUPERAR)
    with tab1:
        st.info("👇 Haz clic en el tiempo (ej: 00:12) para saltar a esa parte del audio.")
        
        col_search, col_clear = st.columns([4,1])
        search_q = col_search.text_input("🔎 Filtrar segmentos:", key="search_input")
        col_clear.button("Limpiar", on_click=clear_search_callback)
        
        # Contenedor con scroll para los segmentos
        with st.container(height=600):
            for seg in st.session_state.segments:
                # Filtrado por búsqueda
                if search_q and search_q.lower() not in seg['text'].lower():
                    continue
                
                c_time, c_text = st.columns([0.15, 0.85])
                
                # Botón de tiempo
                t_start = seg['start']
                t_label = format_timestamp(t_start)
                if c_time.button(f"▶️ {t_label}", key=f"btn_{t_start}"):
                    set_audio_time(t_start)
                    st.rerun()
                
                # Texto del segmento (Corregido por GPT-5 si se activó)
                text_display = seg['text'].strip()
                if search_q: # Resaltar búsqueda
                    text_display = re.sub(f"({re.escape(search_q)})", r"**\1**", text_display, flags=re.IGNORECASE)
                
                c_text.markdown(f"<div style='padding-top: 5px;'>{text_display}</div>", unsafe_allow_html=True)

    # TAB 2: TEXTO PLANO (PARA COPIAR)
    with tab2:
        st.text_area("Texto Completo", st.session_state.transcription, height=400)
        c1, c2 = st.columns(2)
        c1.download_button("💾 Descargar TXT", st.session_state.transcription, "transcripcion.txt")
        with c2: create_copy_button(st.session_state.transcription)

    # TAB 3: RESUMEN
    with tab3:
        if 'summary' in st.session_state:
            st.write(st.session_state.summary)
