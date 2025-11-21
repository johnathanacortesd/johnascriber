import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Transcriptor Pro V8", page_icon="🌑", layout="wide")

# --- 2. INYECCIÓN CSS "NUCLEAR" (MODO OSCURO FORZADO) ---
st.markdown("""
<style>
    /* 1. FORZAR FONDO Y TEXTO GLOBAL */
    [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #000000 !important;
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] {
        background-color: #111111 !important;
        color: #FFFFFF !important;
    }
    
    /* 2. FORZAR TEXTOS GENERALES (Markdown, Párrafos, Títulos) */
    p, h1, h2, h3, h4, h5, h6, span, div, li {
        color: #E0E0E0 !important;
    }

    /* 3. ARREGLAR CAJA DE ESTADO (st.status / Analizando...) */
    /* Esto fuerza que el contenedor del status tenga fondo oscuro y borde */
    .stStatus {
        background-color: #111111 !important;
        border: 1px solid #333 !important;
        color: #FFFFFF !important;
    }
    /* Fuerza el texto dentro del expander del status */
    .stStatus p, .stStatus div, .stStatus span {
        color: #FFFFFF !important;
    }

    /* 4. ARREGLAR INPUTS DE TEXTO (Búsqueda y Contraseña) */
    .stTextInput > div > div > input {
        background-color: #1A1A1A !important;
        color: #FFFFFF !important;
        border: 1px solid #444 !important;
    }
    
    /* 5. ARREGLAR BOTONES (Incluyendo "Limpiar") */
    .stButton > button {
        background-color: #1A1A1A !important;
        color: #FFFFFF !important;
        border: 1px solid #555 !important;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background-color: #333 !important;
        border-color: #00AAFF !important;
        color: #FFFFFF !important;
    }
    /* Botón Primario (Iniciar) */
    .stButton > button[kind="primary"] {
        background-color: #0066CC !important;
        border: none !important;
    }

    /* 6. CAJAS PERSONALIZADAS (Transcripción y Resultados) */
    .transcription-box {
        background-color: #000000 !important;
        color: #DDDDDD !important;
        border: 1px solid #333;
        padding: 20px;
        border-radius: 8px;
        font-family: 'Source Sans Pro', monospace;
        line-height: 1.6;
        max-height: 600px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    
    .search-card {
        background-color: #0A0A0A !important;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 15px;
        margin-bottom: 15px;
    }

    /* Resaltado */
    .highlight {
        background-color: #D32F2F !important; /* Rojo oscuro */
        color: #FFFFFF !important;
        padding: 2px 5px;
        font-weight: bold;
        border-radius: 3px;
    }

    /* Listas de Entidades */
    .entity-box {
        background-color: #111 !important;
        border-left: 4px solid #0066CC;
        padding: 10px;
        margin: 5px 0;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. DEPENDENCIAS ---
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- 4. AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        del st.session_state["password"]

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align: center; color: white;'>🌑 Transcriptor Pro V8</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- 5. UTILS & LOGIC ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
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

# --- 6. FUNCIONES DE PROCESAMIENTO ---
def process_audio(file_bytes, filename):
    if not MOVIEPY_AVAILABLE: return file_bytes, "⚠️ MoviePy no instalado. Usando original."
    try:
        ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(file_bytes)
            in_path = tmp.name
        out_path = in_path + "_opt.mp3"
        try:
            audio = AudioFileClip(in_path)
            audio.write_audiofile(out_path, codec='libmp3lame', bitrate='64k', fps=16000, nbytes=2, ffmpeg_params=["-ac", "1"], verbose=False, logger=None)
            audio.close()
            with open(out_path, 'rb') as f: dat = f.read()
            os.unlink(in_path); os.unlink(out_path)
            return dat, "✅ Audio optimizado (MP3 Mono)."
        except:
            if os.path.exists(in_path): os.unlink(in_path)
            return file_bytes, "⚠️ Falló optimización. Usando original."
    except: return file_bytes, "⚠️ Error archivo."

def ai_polish(text):
    try:
        resp = client.chat.completions.create(
            messages=[{"role": "system", "content": "Corrige tildes y mayúsculas. NO cortes el texto. Devuelve texto completo."}, {"role": "user", "content": text[:25000]}],
            model="llama-3.1-8b-instant", temperature=0.1
        )
        corr = resp.choices[0].message.content.strip()
        return corr if len(corr) > len(text)*0.9 else text
    except: return text

def extract_entities_parallel(text):
    text_ctx = text[:35000]
    prompts = {
        "summary": "Resumen ejecutivo en español.",
        "people": 'Extrae LISTA de nombres de personas. JSON: {"items": ["Nombre1", "Nombre2"]}',
        "brands": 'Extrae LISTA de marcas/entidades. JSON: {"items": ["Marca1", "Entidad2"]}'
    }
    def run_llm(k):
        try:
            r = client.chat.completions.create(
                messages=[{"role": "system", "content": "Extractor JSON preciso." if k!="summary" else "Analista."}, {"role": "user", "content": f"{prompts[k]}\n\nTexto:\n{text_ctx}"}],
                model="llama-3.1-8b-instant", response_format={"type": "json_object"} if k!="summary" else None, temperature=0.1
            )
            return r.choices[0].message.content
        except: return "{}"
    
    with ThreadPoolExecutor(max_workers=3) as ex:
        fs = ex.submit(run_llm, "summary")
        fp = ex.submit(run_llm, "people")
        fb = ex.submit(run_llm, "brands")
        
        def parse(j):
            try: 
                d = json.loads(j)
                l = d if isinstance(d, list) else d.get("items", d.get("people", d.get("brands", [])))
                return list(set([x for x in l if isinstance(x, str)]))
            except: return []

        return {"summary": fs.result(), "people": parse(fp.result()), "brands": parse(fb.result())}

def find_matches(segments, query, ctx=2):
    hits = []
    q = query.lower()
    for i, s in enumerate(segments):
        if q in s['text'].lower():
            start = max(0, i - ctx)
            end = min(len(segments), i + ctx + 1)
            hits.append(segments[start:end])
    return hits

# --- 7. INTERFAZ PRINCIPAL ---
with st.sidebar:
    st.header("⚙️ Configuración")
    st.success("🌑 Modo Oscuro Forzado Activo")
    opt_polish = st.checkbox("Corrección Ortográfica", value=True)
    opt_ctx = st.slider("Contexto de Búsqueda", 1, 5, 2)

st.subheader("📤 Cargar Archivo")
uploaded = st.file_uploader("Archivo de Audio/Video", label_visibility="collapsed")

if st.button("🚀 INICIAR ANÁLISIS", type="primary", use_container_width=True, disabled=not uploaded):
    for k in list(st.session_state.keys()):
        if k not in ['password_correct', 'audio_start_time']: del st.session_state[k]
    
    # El status ahora se verá negro con letras blancas gracias al CSS .stStatus
    with st.status("🔄 Procesando...", expanded=True) as status:
        status.write("🎼 Optimizando audio...")
        raw = uploaded.read()
        proc, msg = process_audio(raw, uploaded.name)
        st.session_state.audio_bytes = proc
        status.write(msg)
        
        status.write("📝 Transcribiendo...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
            tf.write(proc); tf_path = tf.name
        with open(tf_path, "rb") as f:
            # Prompt reforzado
            res = client.audio.transcriptions.create(file=("a.mp3",f), model="whisper-large-v3", language="es", response_format="verbose_json", prompt="Texto exacto español. Palabras clave: Bogotá, López, generó.")
        os.unlink(tf_path)
        
        st.session_state.segs = res.segments
        txt = res.text
        if opt_polish:
            status.write("🤖 IA Puliendo...")
            txt = ai_polish(txt)
        st.session_state.full_text = txt
        
        status.write("🧠 Extrayendo entidades...")
        st.session_state.an = extract_entities_parallel(txt)
        status.update(label="✅ Listo", state="complete", expanded=False)
        st.rerun()

# --- 8. RESULTADOS ---
if 'full_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.audio_bytes, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["🔎 Búsqueda & Texto", "👥 Entidades", "📄 Resumen"])
    
    # TAB 1
    with tabs[0]:
        c1, c2 = st.columns([4, 1])
        q = c1.text_input("Buscar:", key="search_input")
        # Botón Limpiar ahora visible por CSS
        if c2.button("Limpiar"): q = ""
        
        if q:
            res = find_matches(st.session_state.segs, q, opt_ctx)
            if res:
                st.success(f"✅ {len(res)} coincidencias.")
                for match_grp in res:
                    # Contenedor HTML para fondo negro estricto
                    st.markdown('<div class="search-card">', unsafe_allow_html=True)
                    for seg in match_grp:
                        # Columnas dentro del loop
                        ct, cx = st.columns([0.15, 0.85])
                        ct.button(f"▶ {format_timestamp(seg['start'])}", key=f"b_{seg['start']}_{hash(q)}", on_click=set_audio_time, args=(seg['start'],), use_container_width=True)
                        
                        txt = seg['text']
                        if q.lower() in txt.lower():
                            # Resaltado Rojo
                            txt = re.sub(re.escape(q), lambda m: f"<span class='highlight'>{m.group()}</span>", txt, flags=re.IGNORECASE)
                        cx.markdown(f"<div style='color:white; margin-top:5px;'>{txt}</div>", unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.warning("No encontrado.")
        
        st.markdown("### Texto Completo")
        d_txt = st.session_state.full_text
        if q: d_txt = re.sub(re.escape(q), lambda m: f"<span class='highlight'>{m.group()}</span>", d_txt, flags=re.IGNORECASE)
        st.markdown(f"<div class='transcription-box'>{d_txt}</div>", unsafe_allow_html=True)
        st.download_button("💾 Descargar", st.session_state.full_text, "transcripcion.txt")

    # TAB 2
    with tabs[1]:
        an = st.session_state.an
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("### 👥 Personas")
            if an['people']:
                for p in sorted(an['people']): st.markdown(f"<div class='entity-box'>👤 {p}</div>", unsafe_allow_html=True)
            else: st.info("Sin resultados.")
        with col_b:
            st.markdown("### 🏢 Marcas")
            if an['brands']:
                for b in sorted(an['brands']): st.markdown(f"<div class='entity-box'>🏢 {b}</div>", unsafe_allow_html=True)
            else: st.info("Sin resultados.")

    # TAB 3
    with tabs[2]:
        st.info(st.session_state.an.get('summary', '...'))
