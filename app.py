import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import math
import streamlit.components.v1 as components
from datetime import timedelta

# Importar para conversión de audio y manipulación
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
        <h2>Transcriptor Pro - Johnascriptor V2</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA (Long-Form Support)</p>
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

# --- UTILIDADES DE TEXTO ---
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

def export_to_srt(segments):
    srt_content = []
    for i, seg in enumerate(segments, 1):
        start_time = timedelta(seconds=seg['start'])
        end_time = timedelta(seconds=seg['end'])
        start = f"{start_time.seconds//3600:02}:{(start_time.seconds//60)%60:02}:{start_time.seconds%60:02},{start_time.microseconds//1000:03}"
        end = f"{end_time.seconds//3600:02}:{(end_time.seconds//60)%60:02}:{end_time.seconds%60:02},{end_time.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

def clean_encoding(text):
    """Limpia caracteres extraños comunes en transcripciones UTF-8 mal interpretadas."""
    if not text: return ""
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã': 'í', 'Â': '', 'â': '"'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

# --- NÚCLEO DE TRANSCRIPCIÓN ROBUSTA (Chunking) ---
def transcribe_audio_robust(client, file_path, model, language):
    """
    Divide el audio en chunks de 10 minutos para evitar cortes de API y timeouts.
    Une los segmentos resultantes recalculando los timestamps.
    """
    full_segments = []
    full_text = ""
    
    try:
        if MOVIEPY_AVAILABLE:
            audio_clip = AudioFileClip(file_path)
            duration = audio_clip.duration
            # Tamaño del chunk en segundos (10 minutos es seguro para Whisper API)
            chunk_size = 600 
            
            # Si es corto, procesar directo
            if duration < chunk_size:
                with open(file_path, "rb") as f:
                    transcription = client.audio.transcriptions.create(
                        file=(os.path.basename(file_path), f.read()),
                        model=model,
                        language=language,
                        response_format="verbose_json",
                        temperature=0.0,
                        prompt="Transcribir en español correctamente. Usar puntuación."
                    )
                return clean_encoding(transcription.text), transcription.segments
            
            # Si es largo, procesar por chunks
            num_chunks = math.ceil(duration / chunk_size)
            progress_bar = st.progress(0)
            
            for i in range(num_chunks):
                start_time = i * chunk_size
                end_time = min((i + 1) * chunk_size, duration)
                
                # Crear subclip temporal
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_chunk:
                    chunk_path = tmp_chunk.name
                
                # Extraer subclip
                subclip = audio_clip.subclip(start_time, end_time)
                subclip.write_audiofile(chunk_path, codec='libmp3lame', bitrate='64k', verbose=False, logger=None)
                
                # Transcribir chunk
                with open(chunk_path, "rb") as f:
                    resp = client.audio.transcriptions.create(
                        file=("chunk.mp3", f.read()),
                        model=model,
                        language=language,
                        response_format="verbose_json",
                        temperature=0.0,
                        prompt="Continuación de transcripción en español."
                    )
                
                # Ajustar timestamps y agregar
                chunk_text_part = ""
                for seg in resp.segments:
                    seg['start'] += start_time
                    seg['end'] += start_time
                    seg['text'] = clean_encoding(seg['text'])
                    full_segments.append(seg)
                    chunk_text_part += seg['text']
                
                full_text += chunk_text_part
                
                # Limpieza chunk
                os.unlink(chunk_path)
                progress_bar.progress((i + 1) / num_chunks)
            
            audio_clip.close()
            progress_bar.empty()
            return full_text, full_segments
            
        else:
            # Fallback si no hay MoviePy (procesa todo de una, riesgo de corte)
            st.warning("⚠️ MoviePy no detectado. Procesando archivo completo (puede cortarse si es muy largo).")
            with open(file_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), f.read()),
                    model=model,
                    language=language,
                    response_format="verbose_json",
                    prompt="Transcribir audio en español."
                )
            return clean_encoding(transcription.text), transcription.segments

    except Exception as e:
        st.error(f"Error en transcripción: {str(e)}")
        return "", []

# --- CORRECCIÓN DE TEXTO POR LOTES ---
def safe_text_correction(text, client):
    """
    Divide el texto en bloques para que Llama 3 no corte la respuesta por límite de tokens.
    """
    if not text: return ""
    
    # Dividir en bloques de ~3500 caracteres (seguro para contexto de 8k)
    chunk_size = 3500
    text_chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    corrected_full_text = ""
    
    system_prompt = """Eres un corrector experto en español.
    TU TAREA: Corregir ortografía, tildes y puntuación.
    REGLAS CRÍTICAS:
    1. NO resumas. Devuelve el texto LITERAL corregido.
    2. NO agregues comentarios ("Aquí está el texto..."). SOLO el texto.
    3. Respeta la jerga técnica."""
    
    progress_text = st.empty()
    
    try:
        for idx, chunk in enumerate(text_chunks):
            progress_text.text(f"🤖 Corrigiendo parte {idx+1} de {len(text_chunks)}...")
            
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Texto a corregir:\n\n{chunk}"}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.1,
                max_tokens=4000
            )
            corrected_part = response.choices[0].message.content.strip()
            corrected_full_text += corrected_part + " "
        
        progress_text.empty()
        return corrected_full_text.strip()
        
    except Exception as e:
        st.warning(f"⚠️ Error parcial en corrección IA: {e}. Usando texto original.")
        return text

# --- FUNCIONES DE ANÁLISIS (Resumen, Personas, Marcas) ---
def generate_summary(text, client):
    if not text: return ""
    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un experto analista. Resume el texto en español en un párrafo ejecutivo."},
                {"role": "user", "content": f"Resume esto (max 5000 chars):\n{text[:5000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat.choices[0].message.content
    except: return "No se pudo generar resumen."

def extract_json_data(text, client, prompt_type):
    if not text: return []
    prompts = {
        "people": '''Extrae personas y cargos. JSON formato: {"items": [{"name": "Nombre", "role": "Cargo", "context": "Frase"}]}''',
        "brands": '''Extrae marcas u organizaciones. JSON formato: {"items": [{"name": "Nombre", "type": "Tipo", "context": "Frase"}]}'''
    }
    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompts[prompt_type]},
                {"role": "user", "content": f"Analiza:\n{text[:6000]}"} # Limitado para asegurar JSON válido
            ],
            model="llama-3.1-8b-instant", response_format={"type": "json_object"}, temperature=0.0
        )
        data = json.loads(chat.choices[0].message.content)
        return data.get("items", [])
    except: return []

def answer_question(question, context, client, history):
    messages = [{"role": "system", "content": "Responde basándote en el texto proporcionado. Sé preciso."}]
    for qa in history:
        messages.extend([{"role": "user", "content": qa["question"]}, {"role": "assistant", "content": qa["answer"]}])
    # Truncar contexto si es gigante para el chat
    messages.append({"role": "user", "content": f"Texto: {context[:15000]}\n\nPregunta: {question}"})
    
    try:
        resp = client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant")
        return resp.choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- UI PRINCIPAL ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    
    st.divider()
    enable_llama = st.checkbox("🤖 Corrección Ortográfica IA", value=True, help="Puede tardar más en audios largos.")
    enable_summary = st.checkbox("📝 Generar Resumen", value=True)
    enable_entities = st.checkbox("🔍 Extraer Datos (Personas/Marcas)", value=True)
    
    st.divider()
    context_lines = st.slider("Contexto Búsqueda", 1, 5, 2)
    
    if MOVIEPY_AVAILABLE:
        st.success("✅ Motor de Audio: Activo (Chunking habilitado)")
    else:
        st.error("⚠️ Motor de Audio: Inactivo. Instala 'moviepy'")

# --- CARGA Y PROCESAMIENTO ---
st.subheader("1. Cargar Archivo")
uploaded_file = st.file_uploader("Arrastra tu archivo (MP3, M4A, MP4, WAV...)", type=None)

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    # Limpiar estado anterior
    st.session_state.qa_history = []
    
    client = Groq(api_key=api_key)
    
    with st.spinner("🔄 Procesando audio... esto puede tomar unos minutos si el archivo es grande..."):
        # Guardar archivo temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # 1. Transcripción (Con Chunking)
        raw_text, segments = transcribe_audio_robust(client, tmp_path, model_option, "es")
        
        # 2. Corrección (Por lotes)
        final_text = raw_text
        if enable_llama:
            final_text = safe_text_correction(raw_text, client)
        
        # Guardar en sesión
        st.session_state.transcription_text = final_text
        st.session_state.segments = segments # Usamos los segmentos raw para timestamps
        st.session_state.uploaded_audio = uploaded_file.getvalue()
        
        # 3. Análisis Adicional
        if enable_summary:
            st.session_state.summary = generate_summary(final_text, client)
        
        if enable_entities:
            st.session_state.people = extract_json_data(final_text, client, "people")
            st.session_state.brands = extract_json_data(final_text, client, "brands")
        
        # Limpieza
        os.unlink(tmp_path)
        st.success("✅ ¡Completado!")
        st.rerun()

# --- VISUALIZACIÓN ---
if "transcription_text" in st.session_state:
    st.divider()
    st.audio(st.session_state.uploaded_audio, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📝 Transcripción", "📊 Resumen & Chat", "🔍 Entidades"])
    
    # TAB 1: TRANSCRIPCIÓN
    with tabs[0]:
        col1, col2 = st.columns([3, 1])
        search = col1.text_input("Buscar en texto:", key="search_input")
        if col2.button("Limpiar", use_container_width=True): clear_search_callback()
        
        # Lógica de búsqueda y timestamps
        if search:
            hits = [s for s in st.session_state.segments if search.lower() in s['text'].lower()]
            st.info(f"Encontradas {len(hits)} coincidencias.")
            for hit in hits:
                if st.button(f"▶️ {format_timestamp(hit['start'])}: ...{hit['text'][:60]}...", key=f"btn_{hit['start']}"):
                    set_audio_time(hit['start'])
                    st.rerun()
            st.divider()

        st.markdown("### Texto Completo")
        st.text_area("", value=st.session_state.transcription_text, height=400)
        
        c1, c2, c3 = st.columns(3)
        c1.download_button("Descargar TXT", st.session_state.transcription_text, "transcripcion.txt")
        c2.download_button("Descargar SRT", export_to_srt(st.session_state.segments), "subs.srt")
        with c3: create_copy_button(st.session_state.transcription_text)

    # TAB 2: RESUMEN
    with tabs[1]:
        if "summary" in st.session_state:
            st.info(st.session_state.summary)
        
        st.divider()
        st.subheader("Chat con tu Audio")
        
        for chat in st.session_state.qa_history:
            st.markdown(f"**Q:** {chat['question']}")
            st.markdown(f"**A:** {chat['answer']}")
            st.markdown("---")
            
        q = st.text_input("Pregunta algo sobre el audio:")
        if st.button("Preguntar") and q:
            ans = answer_question(q, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history)
            st.session_state.qa_history.append({"question": q, "answer": ans})
            st.rerun()

    # TAB 3: ENTIDADES
    with tabs[2]:
        c_p, c_b = st.columns(2)
        with c_p:
            st.subheader("Personas")
            if "people" in st.session_state:
                for p in st.session_state.people:
                    st.success(f"👤 **{p.get('name')}** ({p.get('role')})")
                    st.caption(p.get('context'))
        with c_b:
            st.subheader("Marcas/Orgs")
            if "brands" in st.session_state:
                for b in st.session_state.brands:
                    st.info(f"🏢 **{b.get('name')}** ({b.get('type')})")
                    st.caption(b.get('context'))
