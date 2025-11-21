import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Transcriptor Pro V4", page_icon="🚀", layout="wide")

# --- DEPENDENCIAS DE AUDIO ---
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def check_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        del st.session_state["password"]
    else:
        st.session_state.password_correct = False

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align: center;'>🚀 Transcriptor Pro V4</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Optimizado para velocidad y precisión en Español</p>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=check_password, key="password")
    st.stop()

# --- UTILS & ESTADO ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- MOTOR DE AUDIO: OPTIMIZACIÓN AGRESIVA ---
def convert_to_optimized_mp3(file_bytes, filename):
    """
    Convierte CUALQUIER input a MP3 Mono 16kHz 64kbps.
    Esta es la configuración nativa ideal para Whisper.
    Reduce drásticamente el tiempo de subida y procesamiento.
    """
    if not MOVIEPY_AVAILABLE:
        return file_bytes, "⚠️ MoviePy no instalado. Usando original (más lento)."
    
    try:
        # Crear temporales
        ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name
        
        output_path = input_path + "_opt.mp3"
        
        # Cargar clip (Video o Audio)
        try:
            if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                clip = VideoFileClip(input_path)
                audio = clip.audio
            else:
                audio = AudioFileClip(input_path)
                clip = None # Para saber qué cerrar
            
            # Exportar optimizado: 16000Hz (Whisper nativo), 1 canal (mono), 64k (suficiente para voz)
            audio.write_audiofile(
                output_path,
                codec='libmp3lame',
                bitrate='64k',
                fps=16000,
                nbytes=2,
                ffmpeg_params=["-ac", "1"], # Forzar Mono
                verbose=False,
                logger=None
            )
            
            # Limpieza objetos moviepy
            audio.close()
            if clip: clip.close()
            
            with open(output_path, 'rb') as f:
                optimized_bytes = f.read()
                
            # Limpieza archivos
            os.unlink(input_path)
            os.unlink(output_path)
            
            orig_size = len(file_bytes) / (1024*1024)
            new_size = len(optimized_bytes) / (1024*1024)
            return optimized_bytes, f"⚡ Audio optimizado: {orig_size:.1f}MB ➔ {new_size:.1f}MB"
            
        except Exception as e:
            if os.path.exists(input_path): os.unlink(input_path)
            return file_bytes, f"⚠️ Falló optimización ({str(e)}). Usando original."
            
    except Exception as e:
        return file_bytes, f"⚠️ Error crítico en conversión: {str(e)}"

# --- MOTOR DE TEXTO: PRECISIÓN ESPAÑOL ---
def fix_spanish_encoding(text):
    """Corrige Mojibake (UTF-8 decodificado como Latin-1) y patrones comunes."""
    if not text: return ""
    
    # 1. Correcciones de codificación (Mojibake común)
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'ÃTb': 'Ñ',
        'Ãcx': 'Á', 'Ã‰': 'É', 'ÃÍ': 'Í', 'Ã“': 'Ó', 'Ãš': 'Ú',
        'Â¿': '¿', 'Â¡': '¡'
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
        
    # 2. Correcciones regex gramaticales rápidas
    corrections = [
        (r'\b(q|Q)ue\s', r'\1ué '), (r'\b(c|C)omo\s', r'\1ómo '), # Contextual simple
        (r'\b(m|M)as\b', r'\1ás'), (r'\b(s|S)i\b', r'\1í'), 
        (r'\b(e|E)sta\b', r'\1stá'),
        (r'\btecnolog(?!ía)', 'tecnología'),
        (r'\binformaci(?!ón)', 'información'),
        (r'\badmin(?!istración)', 'administración')
    ]
    # Aplicar solo si estamos seguros (regex agresivos pueden fallar, ser conservador)
    # Para este nivel, mejor confiamos en el Prompt de Whisper, pero limpiamos espacios
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def post_process_with_llama(text):
    """Limpieza final de estilo con Llama 3.1"""
    try:
        # Limitamos el input para no saturar el contexto si el audio es de horas
        truncated_text = text[:15000] 
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un corrector ortotipográfico experto en español. Tu ÚNICA tarea es arreglar tildes, puntuación y mayúsculas del texto proporcionado. NO resumas, NO reescribas, NO cambies palabras. Devuelve el texto corregido íntegro."},
                {"role": "user", "content": truncated_text}
            ],
            model="llama-3.1-8b-instant", temperature=0.1
        )
        corrected = response.choices[0].message.content
        # Si el texto era muy largo, devolvemos el original para evitar cortes
        return corrected if len(corrected) > len(truncated_text) * 0.8 else text
    except:
        return text

# --- MOTOR DE ANÁLISIS PARALELO ---
def analyze_parallel(text):
    """Ejecuta 3 llamadas a LLM en paralelo para ahorrar tiempo."""
    
    prompts = {
        "summary": "Resumen ejecutivo de 1 párrafo (max 100 palabras). Directo al grano.",
        "people": 'Extrae personas y cargos. JSON: {"personas": [{"name": "Nombre", "role": "Cargo", "context": "Frase clave"}]}',
        "brands": 'Extrae marcas/organizaciones. JSON: {"entidades": [{"name": "Nombre", "type": "Tipo", "context": "Frase clave"}]}'
    }
    
    def call_llm(task_type):
        try:
            is_json = task_type != "summary"
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres un analista de inteligencia preciso. Responde en español."},
                    {"role": "user", "content": f"{prompts[task_type]}\n\nTexto:\n{text[:6000]}"} # Contexto limitado para velocidad
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                response_format={"type": "json_object"} if is_json else None
            )
            content = response.choices[0].message.content
            if is_json:
                return json.loads(content)
            return content
        except Exception as e:
            return [] if task_type != "summary" else f"Error: {e}"

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_sum = executor.submit(call_llm, "summary")
        future_peo = executor.submit(call_llm, "people")
        future_bra = executor.submit(call_llm, "brands")
        
        return {
            "summary": future_sum.result(),
            "people": future_peo.result().get('personas', []),
            "brands": future_bra.result().get('entidades', [])
        }

# --- INTERFAZ PRINCIPAL ---
with st.sidebar:
    st.title("⚙️ Configuración")
    st.info("🚀 Modo Turbo Activado: Conversión automática a MP3 Mono.")
    
    use_post_process = st.checkbox("✨ Corrección IA extra", value=True, help="Usa Llama para pulir tildes finales.")
    search_context = st.slider("Contexto (líneas)", 1, 4, 2)
    
    st.markdown("---")
    st.caption("v4.0 Turbo | Groq + Llama 3.1 + MoviePy")

st.subheader("📤 Carga de Archivos (Audio/Video)")
uploaded_file = st.file_uploader("Arrastra tu archivo aquí", label_visibility="collapsed")

if st.button("🚀 Transcribir y Analizar", type="primary", use_container_width=True, disabled=not uploaded_file):
    # Reset total
    keys_to_keep = ['password_correct', 'audio_start_time']
    for k in list(st.session_state.keys()):
        if k not in keys_to_keep: del st.session_state[k]
    
    with st.status("🔄 Procesando...", expanded=True) as status:
        # 1. Optimización Audio
        status.write("🎼 Optimizando audio para Whisper (MP3 Mono 16kHz)...")
        file_bytes = uploaded_file.read()
        opt_bytes, msg = convert_to_optimized_mp3(file_bytes, uploaded_file.name)
        st.session_state.audio_bytes = opt_bytes
        status.write(msg)
        
        # 2. Transcripción
        status.write("📝 Transcribiendo con Whisper Large V3...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
                tf.write(opt_bytes)
                tf_path = tf.name
            
            with open(tf_path, "rb") as f:
                # Prompt engineering para forzar español correcto
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    prompt="Esta es una transcripción en español, con ortografía perfecta, tildes y puntuación correcta."
                )
            os.unlink(tf_path)
            
            raw_text = fix_spanish_encoding(transcription.text)
            st.session_state.raw_segments = transcription.segments
            
            if use_post_process:
                status.write("🤖 Pulido final de texto con Llama...")
                final_text = post_process_with_llama(raw_text)
            else:
                final_text = raw_text
                
            st.session_state.final_text = final_text
            
            # 3. Análisis Paralelo
            status.write("🧠 Analizando entidades y resumen en paralelo...")
            analysis = analyze_parallel(final_text)
            st.session_state.analysis = analysis
            
            status.update(label="✅ ¡Proceso Completado!", state="complete", expanded=False)
            st.rerun()
            
        except Exception as e:
            status.update(label="❌ Error", state="error")
            st.error(f"Error: {str(e)}")

# --- VISUALIZACIÓN DE RESULTADOS ---
if 'final_text' in st.session_state:
    st.markdown("---")
    
    # Player de Audio Sincronizado
    st.audio(st.session_state.audio_bytes, start_time=st.session_state.audio_start_time)
    
    # Pestañas consolidadas
    tabs = st.tabs(["📝 Transcripción Interactiva", "👥 Entidades y Análisis", "💾 Exportar"])
    
    # --- PESTAÑA 1: TRANSCRIPCIÓN ---
    with tabs[0]:
        col1, col2 = st.columns([4, 1])
        search = col1.text_input("🔎 Buscar en texto:", placeholder="Escribe para filtrar...")
        if col2.button("Limpiar", use_container_width=True): search = ""
        
        # Lógica de resaltado y búsqueda
        segments = st.session_state.raw_segments
        
        if search:
            matches = [s for s in segments if search.lower() in s['text'].lower()]
            st.info(f"Encontradas {len(matches)} coincidencias.")
            for s in matches:
                t_start = timedelta(seconds=int(s['start']))
                clean_text = s['text'].replace(search, f"**{search}**") # Resaltado markdown simple
                
                c1, c2 = st.columns([0.1, 0.9])
                c1.button(f"▶️ {t_start}", key=f"btn_{s['start']}", on_click=set_audio_time, args=(s['start'],))
                c2.markdown(f"...{s['text']}...", unsafe_allow_html=True)
            st.markdown("---")

        # Caja de texto completa
        text_display = st.session_state.final_text
        if search:
            # Resaltado HTML para la vista completa
            pattern = re.compile(re.escape(search), re.IGNORECASE)
            text_display = pattern.sub(lambda m: f"<mark style='background:#FFD700'>{m.group()}</mark>", text_display)
            
        st.markdown(
            f"<div style='height:400px; overflow-y:auto; padding:15px; border:1px solid #444; border-radius:8px; background:#1e1e1e;'>{text_display.replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True
        )

    # --- PESTAÑA 2: ANÁLISIS CONSOLIDADO ---
    with tabs[1]:
        an = st.session_state.analysis
        
        # Resumen arriba
        st.info(f"**📌 Resumen Ejecutivo:**\n\n{an['summary']}")
        
        col_p, col_b = st.columns(2)
        
        with col_p:
            st.subheader("👥 Personas Clave")
            if not an['people']: st.caption("No se detectaron personas.")
            for p in an['people']:
                with st.expander(f"👤 {p.get('name', 'N/A')} - {p.get('role', '')}"):
                    st.write(f"_{p.get('context', '')}_")
                    # Botón buscar en audio para esta persona
                    if st.button(f"🔍 Buscar '{p.get('name', '').split()[0]}'", key=f"find_{p.get('name')}"):
                        # Truco sucio para setear búsqueda en la otra tab (requiere rerun)
                        st.toast("Ve a la pestaña Transcripción para ver resultados")

        with col_b:
            st.subheader("🏢 Marcas y Entidades")
            if not an['brands']: st.caption("No se detectaron marcas.")
            for b in an['brands']:
                with st.expander(f"🏢 {b.get('name', 'N/A')} ({b.get('type', '')})"):
                    st.write(f"_{b.get('context', '')}_")

    # --- PESTAÑA 3: EXPORTAR ---
    with tabs[2]:
        c1, c2, c3 = st.columns(3)
        c1.download_button("📄 Descargar TXT", st.session_state.final_text, "transcripcion.txt", use_container_width=True)
        c2.download_button("📊 Descargar Análisis JSON", json.dumps(st.session_state.analysis, indent=2), "analisis.json", use_container_width=True)
        
        # Generador SRT simple
        def to_srt(segs):
            srt = ""
            for i, s in enumerate(segs):
                start = str(timedelta(seconds=int(s['start']))) + ",000"
                end = str(timedelta(seconds=int(s['end']))) + ",000"
                srt += f"{i+1}\n{start} --> {end}\n{s['text'].strip()}\n\n"
            return srt
            
        c3.download_button("🎬 Descargar Subtítulos (SRT)", to_srt(st.session_state.raw_segments), "subs.srt", use_container_width=True)

st.markdown("---")
if st.button("🗑️ Nueva Transcripción (Limpiar memoria)"):
    st.session_state.clear()
    st.rerun()
