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
st.set_page_config(page_title="Transcriptor Pro V7", page_icon="🎙️", layout="wide")

# --- DEPENDENCIAS ---
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- CSS: MODO OSCURO FORZADO ---
st.markdown("""
<style>
    /* Forzar fondo oscuro global en contenedores clave */
    .element-container, .stMarkdown {
        color: white;
    }
    
    /* CAJA TRANSCRIPCIÓN PRINCIPAL */
    .transcription-box {
        background-color: #0E1117 !important;
        color: #E0E0E0 !important;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 20px;
        font-family: 'Source Sans Pro', sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
        max-height: 600px;
        overflow-y: auto;
        white-space: pre-wrap;
    }

    /* CAJA DE RESULTADO DE BÚSQUEDA (Estilo Tarjeta Negra) */
    .search-card {
        background-color: #161b22 !important;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 15px;
        margin-bottom: 10px;
        color: #c9d1d9 !important;
    }

    /* Highlight en búsqueda */
    .highlight-match {
        background-color: #d29922; /* Dorado oscuro */
        color: #000000;
        padding: 2px 4px;
        border-radius: 3px;
        font-weight: 800;
    }

    /* Estilo para listas de entidades */
    .entity-list-item {
        background-color: #21262d;
        color: #e6edf3;
        padding: 8px 12px;
        margin: 4px 0;
        border-radius: 6px;
        border-left: 4px solid #2f81f7;
        font-size: 0.95rem;
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

if not st.session_state.password_correct:
    st.markdown("<h2 style='text-align: center;'>🎙️ Transcriptor Pro V7</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- ESTADO ---
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

# --- MOTOR AUDIO ---
def process_audio(file_bytes, filename):
    if not MOVIEPY_AVAILABLE: return file_bytes, "⚠️ MoviePy no instalado."
    try:
        ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(file_bytes)
            in_path = tmp.name
        
        out_path = in_path + "_opt.mp3"
        try:
            # Conversión directa y forzada a Audio
            audio = AudioFileClip(in_path)
            audio.write_audiofile(out_path, codec='libmp3lame', bitrate='64k', fps=16000, nbytes=2, ffmpeg_params=["-ac", "1"], verbose=False, logger=None)
            audio.close()
            with open(out_path, 'rb') as f: opt_bytes = f.read()
            os.unlink(in_path); os.unlink(out_path)
            return opt_bytes, "✅ Optimizado."
        except:
            if os.path.exists(in_path): os.unlink(in_path)
            return file_bytes, "⚠️ Falló optimización. Usando original."
    except: return file_bytes, "⚠️ Error archivo."

# --- TEXTO Y CORRECCIÓN ---
def ai_polish_text(text):
    """Corrección ortográfica no destructiva."""
    try:
        # Límite seguro de tokens
        chunk = text[:25000]
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un corrector ortográfico. Tu ÚNICA tarea es poner tildes y corregir mayúsculas en nombres propios (Bogotá, López, etc). NO cortes el texto. Devuelve el texto íntegro."}, 
                {"role": "user", "content": chunk}
            ],
            model="llama-3.1-8b-instant", temperature=0.1
        )
        corrected = resp.choices[0].message.content.strip()
        # Si la IA cortó mucho el texto (error común), descartar corrección
        if len(corrected) < len(chunk) * 0.9: return text
        return corrected
    except: return text

# --- EXTRACCIÓN INTELIGENTE (CORREGIDA) ---
def safe_json_extract(content):
    """Extractor robusto que busca listas en cualquier JSON."""
    try:
        # Limpiar markdown
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        
        # Aplanar respuesta si devuelve un dict
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Buscar cualquier llave que contenga una lista
            for key, val in data.items():
                if isinstance(val, list):
                    items.extend(val)
                    
        # Limpieza de strings
        clean_items = []
        for i in items:
            if isinstance(i, str): clean_items.append(i)
            elif isinstance(i, dict): clean_items.append(i.get('name', i.get('nombre', '')))
        
        return list(set([x for x in clean_items if x])) # Deduplicar y limpiar vacíos
    except:
        return []

def run_analysis_parallel(text):
    # Aumentamos drásticamente el contexto (30k caracteres ~ 20-30 mins)
    # Si el audio es más largo, analiza la primera media hora.
    context_text = text[:35000]
    
    prompts = {
        "summary": "Resumen ejecutivo detallado en español.",
        "people": 'Extrae TODOS los nombres de personas (Nombre y Apellido). Devuelve JSON: {"items": ["Juan Perez", "Maria Gomez"]}',
        "brands": 'Extrae TODAS las marcas, empresas, instituciones, ONGs y ciudades importantes. Devuelve JSON: {"items": ["Google", "Alcaldía de Bogotá", "Coca-Cola"]}'
    }

    def call_ai(task):
        is_json = task != "summary"
        try:
            resp = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres un extractor de datos exhaustivo. Extrae TODAS las menciones."},
                    {"role": "user", "content": f"{prompts[task]}\n\nTexto:\n{context_text}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.1,
                response_format={"type": "json_object"} if is_json else None
            )
            return resp.choices[0].message.content
        except: return "{}"

    with ThreadPoolExecutor(max_workers=3) as exc:
        f_sum = exc.submit(call_ai, "summary")
        f_peo = exc.submit(call_ai, "people")
        f_bra = exc.submit(call_ai, "brands")
        
        return {
            "summary": f_sum.result(),
            "people": safe_json_extract(f_peo.result()),
            "brands": safe_json_extract(f_bra.result())
        }

def get_search_matches(segments, query, ctx_lines=2):
    matches = []
    q = query.lower()
    for i, s in enumerate(segments):
        if q in s['text'].lower():
            start = max(0, i - ctx_lines)
            end = min(len(segments), i + ctx_lines + 1)
            matches.append({'ctx': segments[start:end], 'hit_idx': i})
    return matches

# --- INTERFAZ ---
with st.sidebar:
    st.title("⚙️ Configuración")
    st.info("Modo V7: Dark Mode Forzado & Extracción Profunda")
    do_polish = st.checkbox("Corrección Ortográfica IA", value=True)
    ctx = st.slider("Contexto Búsqueda", 1, 5, 2)

st.subheader("📤 Cargar Archivo")
uploaded = st.file_uploader("Sube tu archivo aquí", label_visibility="collapsed")

if st.button("🚀 PROCESAR", type="primary", use_container_width=True, disabled=not uploaded):
    # Reset
    for k in list(st.session_state.keys()):
        if k not in ['password_correct', 'audio_start_time']: del st.session_state[k]

    with st.status("🔄 Analizando...", expanded=True) as status:
        # 1. Audio
        status.write("🎼 Optimizando audio...")
        raw_bytes = uploaded.read()
        proc_bytes, msg = process_audio(raw_bytes, uploaded.name)
        st.session_state.proc_audio = proc_bytes
        
        # 2. Transcripción
        status.write("📝 Transcribiendo (Whisper V3)...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
                tf.write(proc_bytes); tf_path = tf.name
            
            with open(tf_path, "rb") as f:
                # Prompt reforzado para evitar cortes y malas palabras
                res = client.audio.transcriptions.create(
                    file=("x.mp3", f), model="whisper-large-v3", language="es", response_format="verbose_json",
                    prompt="Transcripción literal en español. Palabras clave: Bogotá, López, generó, mató, año."
                )
            os.unlink(tf_path)
            
            st.session_state.segments = res.segments
            text = res.text
            
            if do_polish:
                status.write("🤖 IA puliendo texto...")
                text = ai_polish_text(text)
            
            st.session_state.full_text = text
            
            # 3. Análisis
            status.write("🧠 Extrayendo entidades (Deep Scan)...")
            st.session_state.analysis_results = run_analysis_parallel(text)
            
            status.update(label="✅ Listo", state="complete", expanded=False)
            st.rerun()
            
        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

# --- RESULTADOS ---
if 'full_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.proc_audio, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["🔎 Transcripción & Búsqueda", "📋 Listado Entidades", "📄 Resumen"])
    
    # TAB 1: BÚSQUEDA OSCURA CORREGIDA
    with tabs[0]:
        c1, c2 = st.columns([4, 1])
        q = c1.text_input("Buscar:", key="search")
        if c2.button("Limpiar"): q = ""
        
        if q:
            results = get_search_matches(st.session_state.segments, q, ctx)
            if results:
                st.success(f"✅ {len(results)} resultados.")
                for res in results:
                    # HTML CONTAINER PARA FORZAR FONDO NEGRO
                    html_content = '<div class="search-card">'
                    
                    for line in res['ctx']:
                        time_str = format_timestamp(line['start'])
                        txt = line['text']
                        
                        # Resaltado manual en HTML
                        if q.lower() in txt.lower():
                            pattern = re.compile(re.escape(q), re.IGNORECASE)
                            txt = pattern.sub(lambda m: f'<span class="highlight-match">{m.group()}</span>', txt)
                        
                        # Fila Flex para alinear botón y texto (Simulado visualmente)
                        # Nota: Streamlit no permite botones dentro de HTML puro facilmente.
                        # Usaremos un truco: Mostramos el texto en HTML negro, y el botón arriba o abajo.
                        # MEJOR ENFOQUE: Renderizar cada linea como columnas de Streamlit pero inyectar CSS a esa fila? No, inestable.
                        # ENFOQUE ACTUAL: Usar st.columns dentro del loop pero el texto va en markdown con style negro.
                        pass # Logic moved below inside the loop
                    
                    # Renderizamos el bloque visualmente
                    # Para que los botones funcionen, debemos usar st.button, no HTML puro.
                    # Así que usaremos st.markdown con divs estilizados linea por linea.
                    
                    with st.container():
                         st.markdown('<div style="background-color: #161b22; padding: 10px; border-radius: 5px; margin-bottom: 10px; border: 1px solid #444;">', unsafe_allow_html=True)
                         for line in res['ctx']:
                             c_time, c_txt = st.columns([0.15, 0.85])
                             
                             # Botón nativo de Streamlit
                             c_time.button(f"▶ {format_timestamp(line['start'])}", key=f"btn_{line['start']}_{hash(q)}", on_click=set_audio_time, args=(line['start'],), use_container_width=True)
                             
                             # Texto HTML forzado blanco
                             txt = line['text']
                             if q.lower() in txt.lower():
                                 pattern = re.compile(re.escape(q), re.IGNORECASE)
                                 txt = pattern.sub(lambda m: f'<span class="highlight-match">{m.group()}</span>', txt)
                             
                             c_txt.markdown(f'<div style="color: #e6edf3; margin-top: 5px; font-family: sans-serif;">{txt}</div>', unsafe_allow_html=True)
                         st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.warning("Sin coincidencias.")
        
        st.markdown("### Texto Completo")
        disp = st.session_state.full_text
        if q:
            pattern = re.compile(re.escape(q), re.IGNORECASE)
            disp = pattern.sub(lambda m: f'<span class="highlight-match">{m.group()}</span>', disp)
        
        st.markdown(f'<div class="transcription-box">{disp}</div>', unsafe_allow_html=True)
        st.download_button("💾 Descargar TXT", st.session_state.full_text, "transcripcion.txt")

    # TAB 2: ENTIDADES
    with tabs[1]:
        res = st.session_state.analysis_results
        ppl = res.get('people', [])
        bnd = res.get('brands', [])
        
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("### 👥 Personas")
            if ppl:
                for p in sorted(ppl):
                    st.markdown(f'<div class="entity-list-item">👤 {p}</div>', unsafe_allow_html=True)
            else:
                st.info("No se encontraron nombres (Intenta con un audio más claro o largo).")
                
        with col_b:
            st.markdown("### 🏢 Marcas / Entidades")
            if bnd:
                for b in sorted(bnd):
                    st.markdown(f'<div class="entity-list-item">🏢 {b}</div>', unsafe_allow_html=True)
            else:
                st.info("No se encontraron marcas.")

    # TAB 3: RESUMEN
    with tabs[2]:
        st.info(st.session_state.analysis_results.get('summary', '...'))
