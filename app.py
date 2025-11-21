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
st.set_page_config(page_title="Transcriptor Pro V6", page_icon="🎙️", layout="wide")

# --- DEPENDENCIAS ---
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- CSS: MODO OSCURO TOTAL Y LEGIBILIDAD ---
st.markdown("""
<style>
    /* Estilo General: Fondo Negro y Letra Blanca */
    .reportview-container .main .block-container {
        padding-top: 2rem;
    }
    
    /* Caja de Transcripción Principal */
    .transcription-box {
        background-color: #000000; /* Negro puro */
        color: #FFFFFF; /* Blanco puro */
        border: 1px solid #333;
        border-radius: 8px;
        padding: 25px;
        font-family: 'Source Sans Pro', sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
        max-height: 600px;
        overflow-y: auto;
        white-space: pre-wrap;
    }

    /* Caja de Resultados de Búsqueda (Igual estilo) */
    .search-result-box {
        background-color: #000000; /* Negro puro */
        color: #FFFFFF;
        border: 1px solid #444;
        border-radius: 6px;
        padding: 15px;
        margin-bottom: 12px;
        font-family: 'Source Sans Pro', sans-serif;
    }

    /* Resaltado de texto encontrado */
    .highlight {
        background-color: #D32F2F; /* Rojo oscuro visible */
        color: #FFFFFF;
        padding: 2px 5px;
        border-radius: 3px;
        font-weight: bold;
    }

    /* Estilo para los Timestamps en búsqueda */
    .timestamp-btn {
        font-weight: bold;
        color: #4CAF50 !important;
    }

    /* Listas de Entidades */
    .entity-item {
        background-color: #1E1E1E;
        padding: 10px;
        margin-bottom: 5px;
        border-radius: 5px;
        border-left: 4px solid #1f77b4;
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
    st.markdown("<h2 style='text-align: center;'>🎙️ Transcriptor Pro V6</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- ESTADO ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []
if 'analysis_results' not in st.session_state: st.session_state.analysis_results = {}

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def format_timestamp(seconds):
    return str(timedelta(seconds=int(seconds)))

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- AUDIO ENGINE ---
def process_audio(file_bytes, filename):
    """Optimización de audio segura."""
    if not MOVIEPY_AVAILABLE:
        return file_bytes, "⚠️ MoviePy no disponible. Usando original."
    
    try:
        file_ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name

        output_path = input_path + "_opt.mp3"
        
        try:
            # Usamos AudioFileClip para todo (ignora video track y sus FPS)
            audio = AudioFileClip(input_path)
            audio.write_audiofile(
                output_path,
                codec='libmp3lame',
                bitrate='64k',     
                fps=16000,
                nbytes=2,
                ffmpeg_params=["-ac", "1"], 
                verbose=False,
                logger=None
            )
            audio.close()
            
            with open(output_path, 'rb') as f:
                optimized_bytes = f.read()
            
            os.unlink(input_path)
            os.unlink(output_path)
            return optimized_bytes, f"✅ Optimizado."
            
        except Exception:
            if os.path.exists(input_path): os.unlink(input_path)
            if os.path.exists(output_path): os.unlink(output_path)
            return file_bytes, "⚠️ No se pudo optimizar. Usando original."
            
    except Exception:
        return file_bytes, "⚠️ Error archivo."

# --- PROCESAMIENTO DE TEXTO (CORREGIDO) ---
def safe_json_parse(content, key_name):
    try:
        # Limpieza básica de bloques de código markdown si la IA los pone
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        if isinstance(data, list): return data
        if isinstance(data, dict):
            if key_name in data: return data[key_name]
            for k, v in data.items():
                if isinstance(v, list): return v
        return []
    except: return []

def ai_polish_text(text):
    """
    Corrección ortográfica inteligente.
    Prompt diseñado para NO cortar texto ni eliminar palabras.
    """
    try:
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un editor de texto experto. Tu tarea es CORREGIR ortografía y acentuación (tildes) faltantes. \nREGLAS:\n1. NO resumas.\n2. NO elimines ninguna palabra.\n3. NO cortes el texto.\n4. Nombres propios como 'Bogotá', 'López', 'García' deben llevar tilde.\n5. Devuelve SOLO el texto corregido completo."}, 
                {"role": "user", "content": text[:25000]} # Aumentado límite seguro
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1
        )
        corrected = resp.choices[0].message.content.strip()
        # Verificación de seguridad: si el texto se redujo más del 20%, algo salió mal, devolvemos original
        if len(corrected) < len(text) * 0.8:
            return text
        return corrected
    except:
        return text

# --- ANÁLISIS PARALELO (MODIFICADO PARA LISTAS LIMPIAS) ---
def run_analysis_parallel(text):
    prompts = {
        "summary": "Crea un resumen ejecutivo en español.",
        "people": 'Extrae SOLO NOMBRES de personas importantes. Devuelve JSON: {"people": ["Nombre Apellido", "Nombre Apellido"]}',
        "brands": 'Extrae SOLO NOMBRES de marcas/instituciones. Devuelve JSON: {"brands": ["Marca 1", "Organización 2"]}'
    }

    def call_ai(task):
        is_json = task != "summary"
        try:
            resp = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres un extractor de datos preciso. Responde JSON." if is_json else "Eres redactor."},
                    {"role": "user", "content": f"{prompts[task]}\n\nTexto:\n{text[:8000]}"}
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

def get_context_segments(segments, text_query, context_lines=2):
    matches = []
    query = text_query.lower()
    for i, seg in enumerate(segments):
        if query in seg['text'].lower():
            start = max(0, i - context_lines)
            end = min(len(segments), i + context_lines + 1)
            matches.append({'context': segments[start:end]})
    return matches

# --- INTERFAZ ---
with st.sidebar:
    st.header("Configuración")
    st.info("⚡ V6 Estable | Dark Mode")
    enable_polish = st.checkbox("Corrección IA (Tildes)", value=True)
    ctx_lines = st.slider("Líneas de contexto", 1, 5, 2)
    st.markdown("---")

st.subheader("📤 Cargar Archivo")
uploaded_file = st.file_uploader("Sube MP3, MP4, WAV...", label_visibility="collapsed")

if st.button("🚀 INICIAR", type="primary", use_container_width=True, disabled=not uploaded_file):
    ks = ['password_correct', 'audio_start_time']
    for k in list(st.session_state.keys()):
        if k not in ks: del st.session_state[k]

    with st.status("🔄 Procesando...", expanded=True) as status:
        status.write("🎼 Optimizando audio...")
        file_bytes = uploaded_file.read()
        proc_bytes, msg = process_audio(file_bytes, uploaded_file.name)
        st.session_state.proc_audio = proc_bytes
        
        status.write("📝 Transcribiendo (Alta Precisión)...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(proc_bytes)
                tmp_path = tmp.name
            
            with open(tmp_path, "rb") as f:
                # PROMPT CRÍTICO: Le damos las palabras clave para que no falle
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", f),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    prompt="Transcripción exacta en español. Palabras clave: Bogotá, Colombia, López, año, mató, generó, administración, pública."
                )
            os.unlink(tmp_path)
            
            # Usamos el texto directo, SIN limpiezas manuales que rompen caracteres
            raw_text = transcription.text
            st.session_state.segments = transcription.segments
            
            if enable_polish:
                status.write("🤖 IA Verificando ortografía...")
                final_text = ai_polish_text(raw_text)
            else:
                final_text = raw_text
                
            st.session_state.full_text = final_text
            
            status.write("🧠 Extrayendo datos...")
            st.session_state.analysis_results = run_analysis_parallel(final_text)
            
            status.update(label="✅ Completado", state="complete", expanded=False)
            st.rerun()

        except Exception as e:
            status.update(label="❌ Error", state="error")
            st.error(str(e))
            st.stop()

# --- VISTA DE RESULTADOS ---
if 'full_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.proc_audio, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📝 Transcripción", "👥 Listado Entidades", "📊 Resumen"])
    
    # --- TAB 1: TRANSCRIPCIÓN Y BÚSQUEDA DARK ---
    with tabs[0]:
        col_s1, col_s2 = st.columns([4, 1])
        search_q = col_s1.text_input("🔎 Buscar palabra exacta:", key="main_search")
        if col_s2.button("Borrar", use_container_width=True): search_q = ""

        if search_q:
            matches = get_context_segments(st.session_state.segments, search_q, ctx_lines)
            if matches:
                st.success(f"✅ {len(matches)} coincidencias.")
                for m in matches:
                    # Contenedor visualmente negro
                    st.markdown('<div class="search-result-box">', unsafe_allow_html=True)
                    for seg in m['context']:
                        c_time, c_text = st.columns([0.15, 0.85])
                        
                        # Botón de tiempo
                        t_label = f"▶ {format_timestamp(seg['start'])}"
                        c_time.button(t_label, key=f"t_{seg['start']}_{hash(search_q)}", on_click=set_audio_time, args=(seg['start'],), use_container_width=True)
                        
                        # Texto con estilo oscuro
                        txt = seg['text']
                        if search_q.lower() in txt.lower():
                            # Resaltado
                            txt = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", txt, flags=re.IGNORECASE)
                        
                        c_text.markdown(f"<span style='color:white;'>{txt}</span>", unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.warning("No se encontraron coincidencias.")

        st.markdown("### Transcripción Completa")
        display_text = st.session_state.full_text
        if search_q:
             display_text = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", display_text, flags=re.IGNORECASE)
        
        st.markdown(f"<div class='transcription-box'>{display_text}</div>", unsafe_allow_html=True)
        
        st.download_button("💾 Descargar TXT", st.session_state.full_text, "transcripcion.txt")

    # --- TAB 2: LISTADOS LIMPIOS ---
    with tabs[1]:
        res = st.session_state.analysis_results
        peop = res.get('people', [])
        brands = res.get('brands', [])
        
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("👥 Personas")
            if peop:
                # Deduplicar lista
                peop = list(dict.fromkeys([p if isinstance(p, str) else p.get('name', '') for p in peop]))
                for p in peop:
                    if p: st.markdown(f"<div class='entity-item'>👤 {p}</div>", unsafe_allow_html=True)
            else:
                st.info("No se detectaron nombres.")

        with c2:
            st.subheader("🏢 Marcas / Entidades")
            if brands:
                # Deduplicar lista
                brands = list(dict.fromkeys([b if isinstance(b, str) else b.get('name', '') for b in brands]))
                for b in brands:
                    if b: st.markdown(f"<div class='entity-item'>🏢 {b}</div>", unsafe_allow_html=True)
            else:
                st.info("No se detectaron marcas.")

    # --- TAB 3: RESUMEN ---
    with tabs[2]:
        st.info(st.session_state.analysis_results.get('summary', 'Pendiente...'))

st.markdown("---")
if st.button("🗑️ Reiniciar"):
    st.session_state.clear()
    st.rerun()
