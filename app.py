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
st.set_page_config(page_title="Transcriptor Pro V5.1", page_icon="🎙️", layout="wide")

# --- DEPENDENCIAS ---
try:
    # Importamos solo AudioFileClip que es lo único necesario incluso para video
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- CSS MODO OSCURO & LEGIBILIDAD ---
st.markdown("""
<style>
    /* Fondo oscuro para la caja de transcripción */
    .transcription-box {
        background-color: #0E1117; /* Negro/Gris muy oscuro */
        color: #E0E0E0; /* Blanco hueso para lectura cómoda */
        border: 1px solid #303030;
        border-radius: 8px;
        padding: 20px;
        font-family: 'Source Sans Pro', sans-serif;
        font-size: 1rem;
        line-height: 1.6;
        max-height: 600px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    /* Resaltado de búsqueda (Naranja oscuro para contraste en negro) */
    .highlight {
        background-color: #d35400; 
        color: #ffffff;
        padding: 2px 4px;
        border-radius: 4px;
        font-weight: bold;
    }
    /* Estilo para contextos en resultados */
    .context-box {
        background-color: #262730; /* Gris oscuro Streamlit */
        padding: 12px;
        border-radius: 5px;
        border-left: 4px solid #fca311;
        margin-bottom: 10px;
        color: #FAFAFA;
    }
    /* Ajuste de botones */
    .stButton button {
        border: 1px solid #444;
    }
</style>
""", unsafe_allow_html=True)

# --- AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        del st.session_state["password"]
    else:
        st.session_state.password_correct = False

if not st.session_state.password_correct:
    st.markdown("<h2 style='text-align: center;'>🎙️ Transcriptor Pro V5.1</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []
if 'analysis_results' not in st.session_state: st.session_state.analysis_results = {}

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def format_timestamp(seconds):
    """Convierte segundos a HH:MM:SS para visualización humana."""
    return str(timedelta(seconds=int(seconds)))

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- PROCESAMIENTO DE AUDIO (CORREGIDO VIDEO_FPS) ---
def process_audio(file_bytes, filename):
    """
    Convierte a MP3 usando SOLO AudioFileClip.
    Esto evita el error 'video_fps' porque tratamos todo como audio desde el inicio.
    """
    if not MOVIEPY_AVAILABLE:
        return file_bytes, "⚠️ MoviePy no disponible. Usando archivo original."

    try:
        file_ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name

        output_path = input_path + "_opt.mp3"
        
        try:
            # Cargamos SIEMPRE como AudioFileClip. 
            # MoviePy es inteligente y extraerá el audio si es un MP4, 
            # ignorando la pista de video y sus atributos problemáticos (FPS).
            audio = AudioFileClip(input_path)

            audio.write_audiofile(
                output_path,
                codec='libmp3lame',
                bitrate='64k',     
                fps=16000,         # Forzamos 16kHz sample rate
                nbytes=2,
                ffmpeg_params=["-ac", "1"], # Forzamos Mono
                verbose=False,
                logger=None
            )
            
            audio.close() # Cerramos explícitamente

            with open(output_path, 'rb') as f:
                optimized_bytes = f.read()

            os.unlink(input_path)
            os.unlink(output_path)

            orig_mb = len(file_bytes) / (1024*1024)
            new_mb = len(optimized_bytes) / (1024*1024)
            return optimized_bytes, f"✅ Optimizado: {orig_mb:.1f}MB ➔ {new_mb:.1f}MB"

        except Exception as e:
            # Limpieza en caso de fallo
            if os.path.exists(input_path): os.unlink(input_path)
            if os.path.exists(output_path): os.unlink(output_path)
            # Si falla moviepy, devolvemos el original sin romper la app
            return file_bytes, f"⚠️ No se pudo optimizar (Formato complejo). Usando original."

    except Exception as e:
        return file_bytes, f"⚠️ Error archivo: {str(e)}"

# --- TEXTO Y JSON ---
def fix_spanish_text(text):
    if not text: return ""
    replacements = {'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.strip()

def safe_json_parse(content, key_name):
    try:
        data = json.loads(content)
        if isinstance(data, list): return data
        if isinstance(data, dict):
            if key_name in data: return data[key_name]
            for k, v in data.items():
                if isinstance(v, list): return v
        return []
    except: return []

# --- CORRECCIÓN IA (FIXED PROMPT) ---
def ai_polish_text(text):
    """Corrige tildes sin agregar charla extra."""
    try:
        # System prompt estricto para evitar "Aquí está tu texto"
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un corrector ortográfico invisible. Tu tarea es arreglar tildes y puntuación en español. REGLA DE ORO: Devuelve ÚNICAMENTE el texto corregido. NO añadidas introducciones, ni explicaciones, ni 'Aquí tienes'. Solo el texto."}, 
                {"role": "user", "content": text[:15000]}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1
        )
        corrected = resp.choices[0].message.content.strip()
        # Doble verificación por si la IA desobedeció
        if corrected.lower().startswith("aquí") or corrected.lower().startswith("claro"):
            return text # Preferimos el original a uno con basura
        return corrected
    except:
        return text

# --- ANÁLISIS PARALELO ---
def run_analysis_parallel(text):
    prompts = {
        "summary": "Crea un resumen ejecutivo detallado en español (máximo 2 párrafos).",
        "people": 'Extrae personas. JSON Array: [{"name": "Nombre", "role": "Cargo", "context": "Cita textual breve"}]',
        "brands": 'Extrae marcas/entidades. JSON Array: [{"name": "Nombre", "type": "Tipo", "context": "Cita textual breve"}]'
    }

    def call_ai(task):
        is_json = task != "summary"
        try:
            resp = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres un analista experto. Responde SOLO en JSON válido." if is_json else "Eres un experto redactor."},
                    {"role": "user", "content": f"{prompts[task]}\n\nTexto:\n{text[:7000]}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                response_format={"type": "json_object"} if is_json else None
            )
            return resp.choices[0].message.content
        except:
            return "[]" if is_json else "No disponible."

    with ThreadPoolExecutor(max_workers=3) as exc:
        f_sum = exc.submit(call_ai, "summary")
        f_peo = exc.submit(call_ai, "people")
        f_bra = exc.submit(call_ai, "brands")
        
        return {
            "summary": f_sum.result(),
            "people": safe_json_parse(f_peo.result(), "people"),
            "brands": safe_json_parse(f_bra.result(), "brands")
        }

def ask_question(question, context, history):
    msgs = [{"role": "system", "content": "Responde basado solo en el texto."}]
    for q, a in history:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": f"Texto:\n{context[:7000]}\n\nPregunta: {question}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except: return "Error de conexión."

def get_context_segments(segments, text_query, context_lines=2):
    matches = []
    query = text_query.lower()
    for i, seg in enumerate(segments):
        if query in seg['text'].lower():
            start = max(0, i - context_lines)
            end = min(len(segments), i + context_lines + 1)
            matches.append({'context': segments[start:end]})
    return matches

# --- INTERFAZ GRÁFICA ---
with st.sidebar:
    st.header("⚙️ Panel de Control")
    st.info("⚡ Modo V5.1 Oscuro")
    enable_ai_polish = st.checkbox("✨ Corrección IA (Tildes)", value=True)
    context_lines = st.slider("🔍 Líneas de contexto", 1, 5, 2)
    st.markdown("---")

st.subheader("📤 Cargar Archivo")
uploaded_file = st.file_uploader("Sube MP3, MP4, WAV...", label_visibility="collapsed")

if st.button("🚀 INICIAR ANÁLISIS", type="primary", use_container_width=True, disabled=not uploaded_file):
    keys_keep = ['password_correct', 'audio_start_time']
    for k in list(st.session_state.keys()):
        if k not in keys_keep: del st.session_state[k]
    st.session_state.qa_history = []

    with st.status("🔄 Procesando...", expanded=True) as status:
        status.write("🎼 Optimizando audio (MP3 64k Mono)...")
        file_bytes = uploaded_file.read()
        proc_bytes, msg = process_audio(file_bytes, uploaded_file.name)
        st.session_state.proc_audio = proc_bytes
        status.write(msg)
        
        status.write("📝 Transcribiendo (Whisper V3)...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(proc_bytes)
                tmp_path = tmp.name
            
            with open(tmp_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    prompt="Español correcto, con tildes."
                )
            os.unlink(tmp_path)
            
            raw_text = fix_spanish_text(transcription.text)
            st.session_state.segments = transcription.segments
            
            if enable_ai_polish:
                status.write("🤖 IA puliendo ortografía...")
                final_text = ai_polish_text(raw_text)
            else:
                final_text = raw_text
                
            st.session_state.full_text = final_text
            
            status.write("🧠 Generando Inteligencia...")
            st.session_state.analysis_results = run_analysis_parallel(final_text)
            
            status.update(label="✅ Listo", state="complete", expanded=False)
            st.rerun()

        except Exception as e:
            status.update(label="❌ Error", state="error")
            st.error(f"Detalle: {str(e)}")
            st.stop()

# --- VISUALIZACIÓN ---
if 'full_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.proc_audio, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📝 Transcripción & Búsqueda", "📊 Resumen & Chat", "👥 Personas & Marcas"])
    
    # --- TAB 1 ---
    with tabs[0]:
        col_s1, col_s2 = st.columns([4, 1])
        search_q = col_s1.text_input("🔎 Buscar:", key="main_search")
        if col_s2.button("Borrar", use_container_width=True): search_q = ""

        if search_q:
            matches = get_context_segments(st.session_state.segments, search_q, context_lines)
            if matches:
                st.success(f"✅ {len(matches)} coincidencias.")
                for m in matches:
                    with st.container():
                        st.markdown("<div class='context-box'>", unsafe_allow_html=True)
                        for seg in m['context']:
                            cols = st.columns([0.15, 0.85])
                            # CORRECCIÓN: Botón con Timestamp visible
                            time_label = f"▶ {format_timestamp(seg['start'])}"
                            cols[0].button(time_label, key=f"s_{seg['start']}_{hash(search_q)}", on_click=set_audio_time, args=(seg['start'],), use_container_width=True)
                            
                            txt = seg['text']
                            if search_q.lower() in txt.lower():
                                txt = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", txt, flags=re.IGNORECASE)
                            
                            cols[1].markdown(f"<div style='color:#E0E0E0; margin-top: 5px;'>{txt}</div>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.warning("No se encontraron coincidencias.")

        st.markdown("### Documento Completo")
        disp_text = st.session_state.full_text
        if search_q:
             disp_text = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", disp_text, flags=re.IGNORECASE)
        
        st.markdown(f"<div class='transcription-box'>{disp_text}</div>", unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        c1.download_button("💾 TXT", st.session_state.full_text, "transcripcion.txt", use_container_width=True)
        srt_content = "".join([f"{i+1}\n{format_timestamp(s['start'])},000 --> {format_timestamp(s['end'])},000\n{s['text'].strip()}\n\n" for i, s in enumerate(st.session_state.segments)])
        c2.download_button("🎬 SRT", srt_content, "sub.srt", use_container_width=True)

    # --- TAB 2 ---
    with tabs[1]:
        res = st.session_state.analysis_results
        st.info(f"📌 **Resumen:**\n\n{res.get('summary', '...')}")
        
        st.markdown("### 💬 Chat")
        for q, a in st.session_state.qa_history:
            st.markdown(f"**P:** {q}\n\n**R:** {a}\n\n---")
            
        with st.form("chat_form"):
            user_q = st.text_input("Pregunta algo:")
            if st.form_submit_button("Enviar") and user_q:
                ans = ask_question(user_q, st.session_state.full_text, st.session_state.qa_history)
                st.session_state.qa_history.append((user_q, ans))
                st.rerun()

    # --- TAB 3 ---
    with tabs[2]:
        res = st.session_state.analysis_results
        peop = res.get('people', [])
        brands = res.get('brands', [])
        
        col_p, col_b = st.columns(2)
        
        with col_p:
            st.subheader("👥 Personas")
            for p in peop:
                with st.expander(f"👤 {p.get('name', '?')} - {p.get('role', '')}"):
                    st.write(f"_{p.get('context', '')}_")
                    p_name = p.get('name', '').split()[0]
                    if st.button(f"🔎 Buscar '{p_name}'", key=f"btn_p_{p_name}"):
                        found = get_context_segments(st.session_state.segments, p_name, 1)
                        if found:
                             s = found[0]['context'][1]
                             st.button(f"▶ Ir a {format_timestamp(s['start'])}", key=f"go_p_{s['start']}", on_click=set_audio_time, args=(s['start'],))
                             st.caption(f"...{s['text']}...")

        with col_b:
            st.subheader("🏢 Marcas")
            for b in brands:
                with st.expander(f"🏢 {b.get('name', '?')} ({b.get('type', '')})"):
                    st.write(f"_{b.get('context', '')}_")
                    b_name = b.get('name', '')
                    if st.button(f"🔎 Buscar '{b_name}'", key=f"btn_b_{b_name}"):
                        found = get_context_segments(st.session_state.segments, b_name, 1)
                        if found:
                             s = found[0]['context'][1]
                             st.button(f"▶ Ir a {format_timestamp(s['start'])}", key=f"go_b_{s['start']}", on_click=set_audio_time, args=(s['start'],))
                             st.caption(f"...{s['text']}...")

st.markdown("---")
if st.button("🗑️ Nueva Transcripción"):
    st.session_state.clear()
    st.rerun()
