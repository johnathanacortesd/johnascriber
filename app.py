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
st.set_page_config(page_title="Transcriptor Pro V5", page_icon="🎙️", layout="wide")

# --- DEPENDENCIAS ---
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# --- CSS PARA LEGIBILIDAD Y ESTILO ---
st.markdown("""
<style>
    /* Estilo para la caja de transcripción: Alto contraste */
    .transcription-box {
        background-color: #f8f9fa; /* Fondo claro */
        color: #212529; /* Texto oscuro casi negro */
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 20px;
        font-family: 'Source Sans Pro', sans-serif;
        font-size: 1rem;
        line-height: 1.6;
        max-height: 600px;
        overflow-y: auto;
        white-space: pre-wrap;
        box-shadow: inset 0 0 10px rgba(0,0,0,0.05);
    }
    /* Resaltado de búsqueda */
    .highlight {
        background-color: #ffc107;
        color: #000;
        padding: 0 4px;
        border-radius: 3px;
        font-weight: bold;
    }
    /* Estilo para contextos */
    .context-box {
        background-color: #e9ecef;
        padding: 10px;
        border-radius: 5px;
        border-left: 4px solid #1f77b4;
        margin-bottom: 10px;
        color: #333;
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
    st.markdown("<h2 style='text-align: center;'>🎙️ Transcriptor Pro V5</h2>", unsafe_allow_html=True)
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

try:
    api_key = st.secrets["GROQ_API_KEY"]
    client = Groq(api_key=api_key)
except KeyError:
    st.error("❌ Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- PROCESAMIENTO DE AUDIO ROBUSTO (CORREGIDO) ---
def process_audio(file_bytes, filename):
    """
    Convierte audio/video a MP3 Mono 16kHz de forma segura.
    Maneja el error de 'video_fps' separando lógica de video y audio.
    """
    if not MOVIEPY_AVAILABLE:
        return file_bytes, "⚠️ MoviePy no disponible. Usando archivo original."

    try:
        # Guardar archivo temporal de entrada
        file_ext = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_in:
            tmp_in.write(file_bytes)
            input_path = tmp_in.name

        output_path = input_path + "_opt.mp3"
        
        try:
            # Lógica separada para evitar errores de atributos
            if file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.mpeg']:
                clip = VideoFileClip(input_path)
                # Extraer audio explícitamente
                audio = clip.audio
                if audio is None:
                    raise ValueError("El video no tiene pista de audio.")
            else:
                clip = None
                audio = AudioFileClip(input_path)

            # Escribir con parámetros explícitos para evitar errores de FPS
            audio.write_audiofile(
                output_path,
                codec='libmp3lame',
                bitrate='64k',     # Suficiente para voz (Whisper)
                fps=16000,         # Sample rate nativo de Whisper
                nbytes=2,
                ffmpeg_params=["-ac", "1"], # Mono
                verbose=False,
                logger=None        # Evita conflictos de barra de progreso
            )

            # Cerrar recursos
            audio.close()
            if clip: clip.close()

            with open(output_path, 'rb') as f:
                optimized_bytes = f.read()

            # Limpieza
            os.unlink(input_path)
            os.unlink(output_path)

            orig_mb = len(file_bytes) / (1024*1024)
            new_mb = len(optimized_bytes) / (1024*1024)
            return optimized_bytes, f"✅ Optimizado: {orig_mb:.1f}MB ➔ {new_mb:.1f}MB"

        except Exception as e:
            # Fallback seguro: si falla la conversión, devolver original
            if os.path.exists(input_path): os.unlink(input_path)
            if os.path.exists(output_path): os.unlink(output_path)
            return file_bytes, f"⚠️ No se pudo optimizar ({str(e)}). Usando original."

    except Exception as e:
        return file_bytes, f"⚠️ Error crítico archivo: {str(e)}"

# --- TEXTO Y JSON ROBUSTO ---
def fix_spanish_text(text):
    """Limpia mojibake y errores comunes."""
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ãed': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
        'Â¿': '¿', 'Â¡': '¡', 'Ã“': 'Ó', 'ÃÍ': 'Í'
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.strip()

def safe_json_parse(content, key_name):
    """
    Parsea JSON intentando manejar tanto objetos como listas directas.
    Soluciona el error: 'list' object has no attribute 'get'
    """
    try:
        data = json.loads(content)
        
        # Caso 1: La IA devolvió una lista directamente [{}, {}]
        if isinstance(data, list):
            return data
            
        # Caso 2: La IA devolvió un objeto {"personas": [{}, {}]}
        if isinstance(data, dict):
            # Intentar buscar la llave pedida, o 'items', o 'data', o devolver la lista si solo hay una llave
            if key_name in data:
                return data[key_name]
            # Si no encuentra la llave exacta, devuelve valores del primer item si es lista
            for k, v in data.items():
                if isinstance(v, list):
                    return v
            return []
            
        return []
    except json.JSONDecodeError:
        return []
    except Exception:
        return []

# --- ANÁLISIS PARALELO (CEREBRO) ---
def run_analysis_parallel(text):
    """Ejecuta Resumen, Personas y Marcas en paralelo."""
    
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
                    {"role": "system", "content": "Eres un analista experto. Responde SOLO en JSON válido si se pide." if is_json else "Eres un experto redactor."},
                    {"role": "user", "content": f"{prompts[task]}\n\nTexto:\n{text[:7000]}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                response_format={"type": "json_object"} if is_json else None
            )
            return resp.choices[0].message.content
        except Exception as e:
            return "[]" if is_json else f"Error: {e}"

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
    try:
        msgs = [{"role": "system", "content": "Responde basado solo en el texto."}]
        for q, a in history:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": f"Texto:\n{context[:7000]}\n\nPregunta: {question}"})
        
        resp = client.chat.completions.create(
            messages=msgs, model="llama-3.1-8b-instant"
        )
        return resp.choices[0].message.content
    except Exception as e: return f"Error: {e}"

def get_context_segments(segments, text_query, context_lines=2):
    """Busca texto en segmentos y devuelve contexto (líneas antes/después)."""
    matches = []
    query = text_query.lower()
    
    for i, seg in enumerate(segments):
        if query in seg['text'].lower():
            start = max(0, i - context_lines)
            end = min(len(segments), i + context_lines + 1)
            matches.append({
                'match_idx': i,
                'context': segments[start:end]
            })
    return matches

# --- INTERFAZ GRÁFICA ---
with st.sidebar:
    st.header("⚙️ Panel de Control")
    st.info("⚡ Modo V5: Optimización de audio automática.")
    
    enable_ai_polish = st.checkbox("✨ Corrección IA (Tildes)", value=True)
    context_lines = st.slider("🔍 Líneas de contexto (Búsqueda)", 1, 5, 2)
    
    st.markdown("---")
    st.write("© Johnascriptor Pro")

st.subheader("📤 Cargar Archivo (Audio/Video)")
uploaded_file = st.file_uploader("Sube MP3, MP4, WAV, M4A...", label_visibility="collapsed")

if st.button("🚀 INICIAR ANÁLISIS COMPLETO", type="primary", use_container_width=True, disabled=not uploaded_file):
    # Limpieza de estado segura
    keep = ['password_correct', 'audio_start_time']
    for k in list(st.session_state.keys()):
        if k not in keep: del st.session_state[k]
    st.session_state.qa_history = []

    with st.status("🔄 Procesando...", expanded=True) as status:
        # 1. Audio
        status.write("🎼 Optimizando audio (MP3 64k Mono)...")
        file_bytes = uploaded_file.read()
        proc_bytes, msg = process_audio(file_bytes, uploaded_file.name)
        st.session_state.proc_audio = proc_bytes
        status.write(msg)
        
        # 2. Transcripción
        status.write("📝 Transcribiendo (Whisper Large V3)...")
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
                    prompt="Español correcto, con tildes y puntuación."
                )
            os.unlink(tmp_path)
            
            # Limpieza texto
            raw_text = fix_spanish_text(transcription.text)
            st.session_state.segments = transcription.segments
            
            if enable_ai_polish:
                status.write("🤖 IA corrigiendo ortografía...")
                try:
                    polished = client.chat.completions.create(
                        messages=[{"role": "system", "content": "Corrige ortografía y tildes. No resumas."}, {"role": "user", "content": raw_text[:15000]}],
                        model="llama-3.1-8b-instant"
                    ).choices[0].message.content
                    final_text = polished
                except:
                    final_text = raw_text
            else:
                final_text = raw_text
                
            st.session_state.full_text = final_text
            
            # 3. Análisis Paralelo
            status.write("🧠 Generando Inteligencia (Resumen, Personas, Marcas)...")
            st.session_state.analysis_results = run_analysis_parallel(final_text)
            
            status.update(label="✅ ¡Completado con éxito!", state="complete", expanded=False)
            st.rerun()

        except Exception as e:
            status.update(label="❌ Error Fatal", state="error")
            st.error(f"Ocurrió un error: {str(e)}")
            st.stop()

# --- VISUALIZACIÓN DE RESULTADOS ---
if 'full_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.proc_audio, start_time=st.session_state.audio_start_time)
    
    # Pestañas organizadas recuperando funcionalidad V1
    tabs = st.tabs(["📝 Transcripción & Búsqueda", "📊 Resumen & Chat", "👥 Personas & Marcas"])
    
    # --- TAB 1: TRANSCRIPCIÓN ---
    with tabs[0]:
        col_s1, col_s2 = st.columns([4, 1])
        search_q = col_s1.text_input("🔎 Buscar en la transcripción:", key="main_search")
        if col_s2.button("Borrar", use_container_width=True): search_q = ""

        if search_q:
            matches = get_context_segments(st.session_state.segments, search_q, context_lines)
            if matches:
                st.success(f"✅ {len(matches)} coincidencias encontradas.")
                for m in matches:
                    with st.container():
                        # Mostrar contexto
                        for seg in m['context']:
                            cols = st.columns([0.1, 0.9])
                            # Botón Play para cada línea de contexto
                            cols[0].button(f"▶", key=f"s_{seg['start']}_{hash(search_q)}", on_click=set_audio_time, args=(seg['start'],))
                            
                            # Resaltado
                            txt = seg['text']
                            if search_q.lower() in txt.lower():
                                txt = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", txt, flags=re.IGNORECASE)
                                cols[1].markdown(f"<div style='background:#fff3cd; color:black; padding:2px;'>{txt}</div>", unsafe_allow_html=True)
                            else:
                                cols[1].markdown(f"<div style='color:#444;'>{txt}</div>", unsafe_allow_html=True)
                        st.markdown("---")
            else:
                st.warning("No se encontraron coincidencias.")

        # Caja de texto completa (Estilo V5 legible)
        disp_text = st.session_state.full_text
        if search_q:
             disp_text = re.sub(re.escape(search_q), lambda x: f"<span class='highlight'>{x.group()}</span>", disp_text, flags=re.IGNORECASE)
        
        st.markdown("### Documento Completo")
        st.markdown(f"<div class='transcription-box'>{disp_text}</div>", unsafe_allow_html=True)
        
        # Botones descarga
        c1, c2 = st.columns(2)
        c1.download_button("💾 Descargar TXT", st.session_state.full_text, "transcripcion.txt", use_container_width=True)
        
        srt_content = ""
        for i, s in enumerate(st.session_state.segments):
            srt_content += f"{i+1}\n{timedelta(seconds=int(s['start']))},000 --> {timedelta(seconds=int(s['end']))},000\n{s['text'].strip()}\n\n"
        c2.download_button("🎬 Descargar SRT", srt_content, "subtitulos.srt", use_container_width=True)

    # --- TAB 2: RESUMEN Y CHAT ---
    with tabs[1]:
        res = st.session_state.analysis_results
        st.info(f"📌 **Resumen Ejecutivo:**\n\n{res.get('summary', 'No disponible')}")
        
        st.markdown("### 💬 Chat con el Audio")
        
        # Mostrar historial
        for q, a in st.session_state.qa_history:
            st.markdown(f"**🙋‍♂️ Pregunta:** {q}")
            st.markdown(f"**🤖 Respuesta:** {a}")
            st.markdown("---")
            
        with st.form("chat_form"):
            user_q = st.text_input("Haz una pregunta sobre el contenido:")
            if st.form_submit_button("Enviar") and user_q:
                ans = ask_question(user_q, st.session_state.full_text, st.session_state.qa_history)
                st.session_state.qa_history.append((user_q, ans))
                st.rerun()

    # --- TAB 3: ENTIDADES (CON PLAYBACK RESTAURADO) ---
    with tabs[2]:
        res = st.session_state.analysis_results
        peop = res.get('people', [])
        brands = res.get('brands', [])
        
        col_p, col_b = st.columns(2)
        
        with col_p:
            st.subheader("👥 Personas")
            if not peop: st.write("No se detectaron personas.")
            for p in peop:
                with st.expander(f"👤 {p.get('name', '?')} - {p.get('role', '')}"):
                    st.write(f"_{p.get('context', '')}_")
                    # Restaurando búsqueda funcional
                    p_name = p.get('name', '').split()[0]
                    if st.button(f"🔎 Buscar menciones de {p_name}", key=f"btn_p_{p_name}"):
                        # Buscar en segmentos
                        found = get_context_segments(st.session_state.segments, p_name, 1)
                        if found:
                            for f in found[:3]: # Mostrar primeras 3
                                s = f['context'][1] # El centro
                                st.button(f"▶ {timedelta(seconds=int(s['start']))} - ...{s['text'][:30]}...", 
                                          key=f"play_p_{s['start']}", 
                                          on_click=set_audio_time, args=(s['start'],))
                        else:
                            st.caption("No encontré menciones exactas en el audio.")

        with col_b:
            st.subheader("🏢 Marcas")
            if not brands: st.write("No se detectaron marcas.")
            for b in brands:
                with st.expander(f"🏢 {b.get('name', '?')} ({b.get('type', '')})"):
                    st.write(f"_{b.get('context', '')}_")
                    b_name = b.get('name', '')
                    if st.button(f"🔎 Buscar menciones de {b_name}", key=f"btn_b_{b_name}"):
                        found = get_context_segments(st.session_state.segments, b_name, 1)
                        if found:
                            for f in found[:3]:
                                s = f['context'][1]
                                st.button(f"▶ {timedelta(seconds=int(s['start']))} - ...{s['text'][:30]}...", 
                                          key=f"play_b_{s['start']}", 
                                          on_click=set_audio_time, args=(s['start'],))

st.markdown("---")
if st.button("🗑️ Limpiar Todo"):
    st.session_state.clear()
    st.rerun()
