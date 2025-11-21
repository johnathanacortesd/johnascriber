import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import math
import streamlit.components.v1 as components
from datetime import timedelta

# Importar para conversión de audio
try:
    from moviepy.editor import AudioFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

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
        <h2>Transcriptor Pro - Johnascriptor V3</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []
if 'brands_search' not in st.session_state:
    st.session_state.brands_search = ""

# --- CALLBACKS ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

def clear_brands_search_callback():
    st.session_state.brands_search = ""

# --- API KEY ---
try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- FUNCIONES AUXILIARES (RECUPERADAS COMPLETAS) ---
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
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in segments]
    return "\n".join(lines)

def export_to_srt(segments):
    srt_content = []
    for i, seg in enumerate(segments, 1):
        start_time = timedelta(seconds=seg['start'])
        end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

def fix_spanish_encoding(text):
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã': 'í', 'Â': '', 'â': '"'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def highlight_text(text, query):
    if not query: return text
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f'<span style="background-color: #fca311; color: #000; padding: 2px 4px; border-radius: 4px; font-weight: bold;">{m.group(0)}</span>', text)

# --- CONVERSOR DE AUDIO (RECUPERADO Y COMPLETO) ---
def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

def universal_audio_converter(file_bytes, filename):
    """
    Conversor robusto original. Fuerza MP3 Mono 16kHz 64kbps.
    """
    try:
        original_size = get_file_size_mb(file_bytes)
        file_ext = os.path.splitext(filename)[1].lower()
        if not file_ext: file_ext = ".mp3" 

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
            tmp_input.write(file_bytes)
            input_path = tmp_input.name
        
        output_path = input_path + "_opt.mp3"
        
        try:
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
                mp3_bytes = f.read()
            
            final_size = get_file_size_mb(mp3_bytes)
            os.unlink(input_path)
            os.unlink(output_path)
            
            return mp3_bytes, True, original_size, final_size
            
        except Exception:
            if os.path.exists(input_path): os.unlink(input_path)
            if os.path.exists(output_path): os.unlink(output_path)
            return file_bytes, False, original_size, original_size
            
    except Exception:
        return file_bytes, False, 0, 0

# --- PROCESO DE TRANSCRIPCIÓN CON CHUNKING (NUEVO + ROBUSTO) ---
def transcribe_with_chunking(client, audio_path, model, language):
    """
    Divide el audio en fragmentos de 10 minutos para evitar cortes,
    pero mantiene la estructura de datos original.
    """
    full_segments = []
    full_text = ""
    
    if MOVIEPY_AVAILABLE:
        try:
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
            chunk_size = 600  # 10 minutos
            
            # Caso corto: Transcripción directa
            if duration < chunk_size:
                with open(audio_path, "rb") as f:
                    transcription = client.audio.transcriptions.create(
                        file=(os.path.basename(audio_path), f.read()),
                        model=model, language=language, response_format="verbose_json",
                        temperature=0.0, prompt="Transcripción exacta en español."
                    )
                return fix_spanish_encoding(transcription.text), transcription.segments
            
            # Caso largo: Chunking
            num_chunks = math.ceil(duration / chunk_size)
            progress_bar = st.progress(0)
            
            for i in range(num_chunks):
                start_time = i * chunk_size
                end_time = min((i + 1) * chunk_size, duration)
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_chunk:
                    chunk_path = tmp_chunk.name
                
                subclip = audio_clip.subclip(start_time, end_time)
                subclip.write_audiofile(chunk_path, codec='libmp3lame', bitrate='64k', verbose=False, logger=None)
                
                with open(chunk_path, "rb") as f:
                    resp = client.audio.transcriptions.create(
                        file=("chunk.mp3", f.read()),
                        model=model, language=language, response_format="verbose_json",
                        temperature=0.0, prompt="Continuación de transcripción en español."
                    )
                
                # Ajustar timestamps para que sean continuos
                chunk_text_part = ""
                for seg in resp.segments:
                    seg['start'] += start_time
                    seg['end'] += start_time
                    seg['text'] = fix_spanish_encoding(seg['text'])
                    full_segments.append(seg)
                    chunk_text_part += seg['text']
                
                full_text += chunk_text_part
                os.unlink(chunk_path)
                progress_bar.progress((i + 1) / num_chunks)
            
            audio_clip.close()
            progress_bar.empty()
            return full_text, full_segments
            
        except Exception as e:
            st.warning(f"Fallo en chunking ({str(e)}). Intentando método directo...")
            # Fallback al método directo
            with open(audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), f.read()),
                    model=model, language=language, response_format="verbose_json"
                )
            return fix_spanish_encoding(transcription.text), transcription.segments
    else:
        # Sin MoviePy, método directo
        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model=model, language=language, response_format="verbose_json"
            )
        return fix_spanish_encoding(transcription.text), transcription.segments

# --- CORRECCIÓN DE TEXTO POR LOTES (MEJORA) ---
def safe_batched_correction(text, client):
    """
    Mejora: Divide el texto en lotes para que Llama no corte la respuesta.
    """
    if not text: return ""
    chunk_size = 3500
    text_chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    corrected_full_text = ""
    
    system_prompt = """Eres un corrector ortográfico experto.
TU TAREA: Corregir ÚNICAMENTE tildes, puntuación y errores ortográficos.
REGLAS:
1. NO resumas.
2. NO cambies palabras por sinónimos.
3. Devuelve SOLO el texto corregido."""
    
    progress_text = st.empty()
    
    try:
        for idx, chunk in enumerate(text_chunks):
            progress_text.text(f"🤖 Puliento ortografía parte {idx+1} de {len(text_chunks)}...")
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk}
                ],
                model="llama-3.1-8b-instant", temperature=0.1, max_tokens=4000
            )
            corrected_full_text += response.choices[0].message.content.strip() + " "
        
        progress_text.empty()
        return corrected_full_text.strip()
    except Exception as e:
        st.warning(f"⚠️ Error parcial en IA: {e}. Usando texto original.")
        return text

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(text, client):
    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto. Crea un resumen ejecutivo en español."},
                {"role": "user", "content": f"Resumen de (max 150 palabras):\n{text[:6000]}"}
            ], model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat.choices[0].message.content
    except: return "Error al generar resumen."

def extract_json_data(text, client, prompt_type):
    prompts = {
        "people": '''Extrae personas y roles. JSON válido: {"items": [{"name": "Nombre", "role": "Cargo", "context": "Frase"}]}''',
        "brands": '''Extrae marcas/entidades. JSON válido: {"items": [{"name": "Nombre", "type": "Tipo", "context": "Frase"}]}'''
    }
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": prompts[prompt_type]}, {"role": "user", "content": f"{text[:6000]}"}],
            model="llama-3.1-8b-instant", response_format={"type": "json_object"}, temperature=0.0
        )
        data = json.loads(chat.choices[0].message.content)
        return data.get("items", [])
    except: return []

def answer_question(question, transcription_text, client, conversation_history):
    messages = [{"role": "system", "content": "Responde preguntas sobre la transcripción. Sé preciso."}]
    for qa in conversation_history:
        messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
    messages.append({"role": "user", "content": f"Texto: {transcription_text[:15000]}\n\nPregunta: {question}"})
    try:
        return client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return str(e)

# --- UI PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    st.markdown("---")
    enable_llama = st.checkbox("🤖 Corrección Ortográfica", value=True)
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    enable_entities = st.checkbox("🔍 Extraer datos", value=True)
    
    st.markdown("---")
    if MOVIEPY_AVAILABLE:
        st.success("✅ Conversión y Chunking Activos")
    else:
        st.warning("⚠️ MoviePy no instalado. Funciones limitadas.")

# --- CARGA Y PROCESAMIENTO ---
st.subheader("📤 Sube tu archivo de audio o video")
uploaded_file = st.file_uploader("Selecciona archivo", type=["mp3", "mp4", "wav", "m4a", "ogg"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    # Reset de variables
    st.session_state.qa_history = []
    st.session_state.brands_search = ""
    client = Groq(api_key=api_key)

    # 1. Optimización / Conversión (Recuperado)
    with st.spinner("🔄 Optimizando archivo..."):
        file_bytes = uploaded_file.getvalue()
        if MOVIEPY_AVAILABLE:
            processed_bytes, was_converted, orig_mb, final_mb = universal_audio_converter(file_bytes, uploaded_file.name)
            if was_converted:
                reduction = ((orig_mb - final_mb) / orig_mb * 100) if orig_mb > 0 else 0
                st.info(f"✅ Optimizado: {orig_mb:.2f}MB -> {final_mb:.2f}MB ({reduction:.0f}%)")
            else:
                st.warning("Usando original (no se pudo optimizar).")
        else:
            processed_bytes = file_bytes

        st.session_state.uploaded_audio_bytes = processed_bytes

        # Guardar temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
            tmp.write(processed_bytes)
            tmp_path = tmp.name

    # 2. Transcripción con Chunking (Mejora)
    with st.spinner("🔄 Transcribiendo por fragmentos..."):
        raw_text, segments = transcribe_with_chunking(client, tmp_path, model_option, "es")
        os.unlink(tmp_path)

    # 3. Corrección por Lotes (Mejora)
    final_text = raw_text
    if enable_llama:
        final_text = safe_batched_correction(raw_text, client)

    st.session_state.transcription = final_text
    st.session_state.segments = segments

    # 4. Análisis Extra
    if enable_summary:
        with st.spinner("🧠 Generando resumen..."):
            st.session_state.summary = generate_summary(final_text, client)
    if enable_entities:
        with st.spinner("🔍 Extrayendo entidades..."):
            st.session_state.people = extract_json_data(final_text, client, "people")
            st.session_state.brands = extract_json_data(final_text, client, "brands")

    st.success("✅ ¡Proceso Completado!")
    st.rerun()

# --- VISUALIZACIÓN DE RESULTADOS ---
if 'transcription' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)

    tabs = st.tabs(["📝 Transcripción", "📊 Resumen y Chat", "👥 Personas", "🏢 Marcas"])

    # --- TAB 1: TRANSCRIPCIÓN + BÚSQUEDA CONTEXTUAL ---
    with tabs[0]:
        c1, c2 = st.columns([3, 1])
        search_query = c1.text_input("🔎 Buscar:", key="search_input")
        # Fix: on_click para limpiar
        c2.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True)

        if search_query:
            st.info(f"Resultados para: '{search_query}'")
            segments = st.session_state.segments
            found_any = False
            
            for i, seg in enumerate(segments):
                if search_query.lower() in seg['text'].lower():
                    found_any = True
                    # Contexto: Anterior - Actual - Siguiente
                    prev_txt = segments[i-1]['text'] if i > 0 else ""
                    curr_txt = highlight_text(seg['text'], search_query)
                    next_txt = segments[i+1]['text'] if i < len(segments)-1 else ""
                    
                    with st.container():
                        col_play, col_txt = st.columns([0.1, 0.9])
                        col_play.button("▶", key=f"play_{i}", on_click=set_audio_time, args=(seg['start'],))
                        
                        html_block = f"""
                        <div style="background-color: #1E1E1E; padding: 10px; border-radius: 5px; border-left: 4px solid #fca311; color: #ddd; font-size: 0.9rem;">
                            <div style="opacity: 0.6; font-size: 0.8rem; margin-bottom: 4px;">... {prev_txt}</div>
                            <div style="font-weight: 500; color: #fff;">{curr_txt}</div>
                            <div style="opacity: 0.6; font-size: 0.8rem; margin-top: 4px;">{next_txt} ...</div>
                            <div style="margin-top: 6px; font-size: 0.75rem; color: #888;">⏱️ {format_timestamp(seg['start'])}</div>
                        </div>
                        """
                        col_txt.markdown(html_block, unsafe_allow_html=True)
                        st.markdown("---")
            
            if not found_any: st.warning("No se encontraron coincidencias.")

        st.markdown("### Texto Completo")
        st.text_area("", value=st.session_state.transcription, height=400)
        
        # Botones de descarga (Recuperados)
        col_d1, col_d2, col_d3, col_d4 = st.columns([1, 1, 1, 1])
        col_d1.download_button("💾 TXT Simple", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        col_d2.download_button("💾 TXT Tiempos", format_transcription_with_timestamps(st.session_state.segments), "transcripcion_tiempos.txt", use_container_width=True)
        col_d3.download_button("💾 SRT Subs", export_to_srt(st.session_state.segments), "subs.srt", use_container_width=True)
        with col_d4: create_copy_button(st.session_state.transcription)

    # --- TAB 2: RESUMEN ---
    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### Resumen Ejecutivo")
            st.info(st.session_state.summary)
        
        st.divider()
        st.subheader("Chat con el audio")
        for qa in st.session_state.qa_history:
            st.markdown(f"**P:** {qa['question']}")
            st.markdown(f"**R:** {qa['answer']}")
            st.markdown("---")
        
        with st.form("chat_form", clear_on_submit=True):
            user_q = st.text_area("Pregunta:")
            if st.form_submit_button("Enviar") and user_q:
                ans = answer_question(user_q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                st.session_state.qa_history.append({'question': user_q, 'answer': ans})
                st.rerun()

    # --- TAB 3: PERSONAS ---
    with tabs[2]:
        if 'people' in st.session_state:
            for p in st.session_state.people:
                st.success(f"👤 {p.get('name')} | {p.get('role')}")
                st.caption(p.get('context'))

    # --- TAB 4: MARCAS ---
    with tabs[3]:
        if 'brands' in st.session_state:
            for b in st.session_state.brands:
                st.info(f"🏢 {b.get('name')} | {b.get('type')}")
                st.caption(b.get('context'))
