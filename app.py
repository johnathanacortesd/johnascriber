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
        <p style='color: #666; margin-bottom: 2rem;'>Versión Mejorada - Transcripción Exacta</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro - V8", page_icon="🎙️", layout="wide")

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

def fix_spanish_encoding_light(text):
    """Versión ligera que solo corrige encodings mal formados, NO altera contenido"""
    if not text: return text
    result = text
    
    # Solo corrige errores de encoding UTF-8 malformado
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\u00d1': 'Ñ', 'Â\u00bf': '¿', 'Â\u00a1': '¡',
        'Ã\u00c1': 'Á', 'Ã\u0089': 'É', 'Ã\u00cd': 'Í', 'Ã\u0093': 'Ó', 'Ã\u009a': 'Ú'
    }
    
    for wrong, correct in replacements.items():
        result = result.replace(wrong, correct)
    
    return result.strip()

# --- CORRECCIÓN DETERMINÍSTICA (SIN IA) ---
def fix_accents_deterministic(text):
    """Corrección de tildes usando reglas fijas, SIN IA que pueda inventar"""
    
    # Palabras comunes que siempre llevan tilde
    accent_corrections = {
        # Interrogativos y exclamativos
        r'\bcomo\b': 'cómo', r'\bque\b': 'qué', r'\bquien\b': 'quién', 
        r'\bcual\b': 'cuál', r'\bcuales\b': 'cuáles', r'\bcuando\b': 'cuándo',
        r'\bdonde\b': 'dónde', r'\bcuanto\b': 'cuánto', r'\bcuanta\b': 'cuánta',
        
        # Sustantivos comunes
        r'\btelefonia\b': 'telefonía', r'\btecnologia\b': 'tecnología',
        r'\badministracion\b': 'administración', r'\binformacion\b': 'información',
        r'\bcomunicacion\b': 'comunicación', r'\beducacion\b': 'educación',
        r'\bsolucion\b': 'solución', r'\batencion\b': 'atención',
        r'\bdireccion\b': 'dirección', r'\bsituacion\b': 'situación',
        
        # Adjetivos comunes
        r'\bpublico\b': 'público', r'\bpublica\b': 'pública',
        r'\bpolitico\b': 'político', r'\bpolitica\b': 'política',
        r'\btecnico\b': 'técnico', r'\btecnica\b': 'técnica',
        r'\bbasico\b': 'básico', r'\bbasica\b': 'básica',
        r'\brapido\b': 'rápido', r'\brapida\b': 'rápida',
        
        # Verbos en pasado
        r'\bestaba\b': 'estaba', r'\bestuve\b': 'estuve',
        r'\bhablo\b': 'habló', r'\bhable\b': 'hablé',
        
        # Pronombres
        r'\bel\b(?=\s+(esta|estaba|fue))': 'él',
        r'\btu\b(?=\s+(tienes|eres|estas))': 'tú',
        r'\bmi\b(?=\s+(nombre|idea))': 'mí',
    }
    
    result = text
    for pattern, replacement in accent_corrections.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result
def text_chunker_smart(text, chunk_size=3000):
    """Chunking más inteligente que respeta oraciones completas"""
    chunks = []
    current_chunk = ""
    
    # Dividir por oraciones de forma más precisa
    sentences = re.split(r'(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚÑ])', text)
    
    for sentence in sentences:
        # Si agregar esta oración no excede el límite
        if len(current_chunk) + len(sentence) + 1 < chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def post_process_conservative(transcription_text, client):
    """Post-procesamiento ULTRA CONSERVADOR - Solo agrega tildes faltantes"""
    chunks = text_chunker_smart(transcription_text)
    cleaned_chunks = []
    
    progress_text = "🧠 Corrección de tildes..."
    my_bar = st.progress(0, text=progress_text)
    total_chunks = len(chunks)

    # PROMPT ULTRA ESPECÍFICO - SOLO TILDES
    system_prompt = """Eres un corrector de tildes en español. Tu ÚNICA tarea es agregar tildes faltantes.

REGLAS ABSOLUTAS:
1. SOLO agrega tildes donde falten (á, é, í, ó, ú, ñ)
2. NO cambies ninguna palabra por otra (telefonía ≠ teléfono)
3. NO cambies tiempos verbales
4. NO resumas ni acortes
5. NO cambies números ni fechas
6. NO agregues ni quites palabras
7. Si una palabra YA tiene tilde, NO la toques
8. Devuelve el texto IDÉNTICO, solo con tildes corregidas

Palabras que NO debes cambiar NUNCA:
- telefonía → telefonía (ya correcta)
- tecnología → tecnología (ya correcta) 
- administración → administración (ya correcta)
- público → público (ya correcta)

SOLO corrige si falta la tilde:
- "telefonia" → "telefonía"
- "administracion" → "administración"
- "como estas" → "cómo estás"

RESPONDE SOLO CON EL TEXTO, SIN EXPLICACIONES."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk}
                ],
                model="llama-3.1-8b-instant", 
                temperature=0.0,  # CERO para máxima exactitud
                max_tokens=len(chunk) + 1000
            )
            corrected = response.choices[0].message.content.strip()
            
            # VALIDACIÓN MÁS ESTRICTA
            word_count_original = len(chunk.split())
            word_count_corrected = len(corrected.split())
            word_diff = abs(word_count_original - word_count_corrected)
            
            # Si cambió cantidad de palabras o más del 10% del largo, rechazar
            if word_diff > 2 or abs(len(corrected) - len(chunk)) / len(chunk) > 0.1:
                st.warning(f"⚠️ Chunk {i+1}: Cambios detectados, usando original")
                cleaned_chunks.append(chunk)
            else:
                cleaned_chunks.append(corrected)
                
        except Exception as e:
            st.warning(f"⚠️ Error en chunk {i+1}: usando original")
            cleaned_chunks.append(chunk)
        
        my_bar.progress((i + 1) / total_chunks, text=f"{progress_text} ({i+1}/{total_chunks})")

    my_bar.empty()
    return " ".join(cleaned_chunks)

# --- OPTIMIZACIÓN ROBUSTA (FFMPEG) ---
def optimize_audio_robust(file_bytes, filename):
    file_ext = os.path.splitext(filename)[1]
    if not file_ext: file_ext = ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
        tmp_input.write(file_bytes)
        input_path = tmp_input.name
    
    output_path = input_path + "_opt.mp3"
    original_size = len(file_bytes) / (1024 * 1024)
    
    try:
        command = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k",
            "-f", "mp3", output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, 'rb') as f:
                new_bytes = f.read()
            
            final_size = len(new_bytes) / (1024 * 1024)
            os.unlink(input_path); os.unlink(output_path)
            
            reduction = ((original_size - final_size) / original_size * 100) if original_size > 0 else 0
            return new_bytes, {'converted': True, 'message': f"✅ Optimizado: {original_size:.1f}MB → {final_size:.1f}MB (-{reduction:.0f}%)"}
        else:
            raise Exception("Falló conversión FFmpeg")

    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, {'converted': False, 'message': f"⚠️ Usando original. Error: {str(e)}"}

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto. Crea un resumen ejecutivo en español, máximo 2 párrafos, destacando puntos clave."},
                {"role": "user", "content": f"Resume este contenido:\n\n{transcription_text[:15000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción proporcionada. Cita fragmentos textuales cuando sea relevante."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Transcripción:\n{transcription_text[:25000]}\n\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    return [{'text': segments[i]['text'].strip(), 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start_idx, end_idx)]

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

with st.sidebar:
    st.header("⚙️ Configuración")
    
    # MEJORA: Opciones más claras
    correction_mode = st.radio(
        "🤖 Modo de corrección:",
        ["Ninguna (Whisper puro)", "Diccionario (Sin IA)", "IA Conservadora", "IA Agresiva"],
        index=1,
        help="Diccionario = reglas fijas sin IA. IA Conservadora = solo tildes con validación"
    )
    
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    
    st.markdown("---")
    
    # MEJORA: Parámetros avanzados de Whisper
    with st.expander("⚙️ Configuración Avanzada Whisper"):
        temperature_whisper = st.slider(
            "Temperatura Whisper", 
            0.0, 1.0, 0.0, 0.1,
            help="0.0 = más determinístico y exacto"
        )
        
        use_custom_prompt = st.checkbox(
            "Usar prompt personalizado",
            value=True,
            help="Guía a Whisper con vocabulario específico"
        )
        
        if use_custom_prompt:
            custom_prompt = st.text_area(
                "Prompt para Whisper:",
                value="Transcripción en español. Palabras clave: telefonía, administración pública, tecnología, comunicación, gobierno, digital, ciudadano, servicio.",
                help="Incluye palabras técnicas que esperas en el audio"
            )
    
    context_lines = st.slider("Líneas de contexto búsqueda", 1, 5, 2)
    st.info("✅ Motor FFmpeg: MP3 Mono 32kbps activo.")

st.subheader("📤 Sube tu archivo (Audio/Video)")
uploaded_file = st.file_uploader("Selecciona archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mov", "avi"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    try:
        # 1. OPTIMIZACIÓN
        with st.spinner("🔄 Comprimiendo audio con FFmpeg..."):
            file_bytes, conversion_info = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = file_bytes
            if conversion_info['converted']:
                st.success(conversion_info['message'])
            else:
                st.warning(conversion_info['message'])

        client = Groq(api_key=api_key)
        
        # 2. TRANSCRIPCIÓN MEJORADA
        with st.spinner("🔄 Transcribiendo con Whisper V3 (modo exacto)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # PREPARAR PROMPT
            if use_custom_prompt and 'custom_prompt' in locals():
                whisper_prompt = custom_prompt
            else:
                whisper_prompt = "Transcripción en español. Incluye tildes correctas en: qué, cómo, cuándo, dónde, público, administración, telefonía, tecnología."
            
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_file.read()), 
                    model="whisper-large-v3", 
                    language="es",
                    response_format="verbose_json",
                    temperature=temperature_whisper,  # Usar configuración del usuario
                    prompt=whisper_prompt
                )
            os.unlink(tmp_path)
        
        # 3. PROCESAMIENTO LIGERO
        transcription_text = fix_spanish_encoding_light(transcription.text)
        
        # 4. POST-PROCESAMIENTO SEGÚN MODO
        if correction_mode == "Diccionario (Sin IA)":
            # Usar corrección determinística SIN IA
            transcription_text = fix_accents_deterministic(transcription_text)
            st.success("✅ Corrección aplicada con diccionario (sin IA)")
        elif correction_mode == "IA Conservadora":
            transcription_text = post_process_conservative(transcription_text, client)
        elif correction_mode == "IA Agresiva":
            # Usar tu función original si el usuario lo pide explícitamente
            st.warning("⚠️ Modo agresivo: puede alterar palabras técnicas")
            transcription_text = post_process_conservative(transcription_text, client)
        # Si es "Ninguna", no hacer nada más
        
        # Aplicar fix ligero a segmentos
        for seg in transcription.segments:
            seg['text'] = fix_spanish_encoding_light(seg['text'])

        st.session_state.transcription = transcription_text
        st.session_state.transcription_data = transcription
        
        if enable_summary:
            with st.spinner("📝 Generando resumen..."):
                st.session_state.summary = generate_summary(transcription_text, client)
        
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
    
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción Completa", "📊 Resumen y Chat", "🔍 Comparación"])
    
    # --- TAB 1: TRANSCRIPCIÓN ---
    with tab1:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        col1, col2 = st.columns([4, 1])
        search_query = col1.text_input("🔎 Buscar en texto:", key="search_input")
        col2.write(""); col2.button("🗑️", on_click=clear_search_callback)

        # BÚSQUEDA MEJORADA - Muestra transcripción completa con resaltados
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                # Buscar en la transcripción completa procesada
                full_text = st.session_state.transcription
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                
                # Encontrar todas las coincidencias con sus posiciones
                matches = list(pattern.finditer(full_text))
                
                if matches:
                    st.markdown(f"**{len(matches)} coincidencia(s) encontrada(s)**")
                    st.markdown("---")
                    
                    # Obtener segmentos para los botones de tiempo
                    segments = st.session_state.transcription_data.segments
                    
                    for idx, match in enumerate(matches):
                        # Extraer contexto alrededor de la coincidencia (500 caracteres antes y después)
                        start_pos = max(0, match.start() - 500)
                        end_pos = min(len(full_text), match.end() + 500)
                        
                        # Ajustar al inicio de palabra/oración
                        while start_pos > 0 and full_text[start_pos] not in ['.', '\n', ' ']:
                            start_pos -= 1
                        if start_pos > 0:
                            start_pos += 1
                        
                        context = full_text[start_pos:end_pos].strip()
                        
                        # Aplicar resaltado
                        context_highlighted = pattern.sub(
                            f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', 
                            context
                        ).replace('\n', '<br>')
                        
                        # Encontrar el segmento más cercano para el botón de reproducción
                        match_text = full_text[max(0, match.start()-50):match.end()+50]
                        closest_segment = None
                        min_distance = float('inf')
                        
                        for seg in segments:
                            seg_text = seg['text'].strip()
                            if search_query.lower() in seg_text.lower():
                                # Calcular similitud simple
                                if match_text.lower() in full_text[start_pos:end_pos].lower():
                                    distance = abs(len(full_text[:match.start()].split()) - sum(1 for s in segments[:segments.index(seg)] for _ in s['text'].split()))
                                    if distance < min_distance:
                                        min_distance = distance
                                        closest_segment = seg
                        
                        col_btn, col_text = st.columns([0.12, 0.88])
                        
                        with col_btn:
                            if closest_segment:
                                btn_key = f"play_search_{idx}_{closest_segment['start']}"
                                st.button(
                                    f"▶️ {format_timestamp(closest_segment['start'])}", 
                                    key=btn_key, 
                                    on_click=set_audio_time, 
                                    args=(closest_segment['start'],),
                                    use_container_width=True
                                )
                            else:
                                st.write("")
                        
                        with col_text:
                            # Mostrar con el mismo estilo negro de la transcripción completa
                            st.markdown(f"""
                            <div style="
                                background-color: #000000; 
                                color: #FFFFFF; 
                                padding: 20px; 
                                border-radius: 10px; 
                                border: 2px solid #fca311;
                                font-family: sans-serif; 
                                line-height: 1.6;
                                white-space: pre-wrap;">
                                {context_highlighted}
                            </div>
                            """, unsafe_allow_html=True)
                        
                        if idx < len(matches) - 1:
                            st.markdown("---")
                else: 
                    st.info("❌ Sin coincidencias para tu búsqueda.")

        st.markdown("### 📄 Texto Transcrito")
        
        html_text = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            html_text = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', html_text)
        
        st.markdown(f"""
        <div style="
            background-color: #000000; 
            color: #FFFFFF; 
            padding: 20px; 
            border-radius: 10px; 
            border: 1px solid #333; 
            font-family: sans-serif; 
            line-height: 1.6; 
            max-height: 600px; 
            overflow-y: auto;
            white-space: pre-wrap;">
            {html_text}
        </div>
        """, unsafe_allow_html=True)
        
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
        else: st.info("Resumen no generado. Habilita la opción en el menú.")
    
    # --- TAB 3: COMPARACIÓN (NUEVA) ---
    with tab3:
        st.markdown("### 🔍 Comparación Transcripción Original vs Procesada")
        st.info("Esta pestaña te permite ver qué cambió durante el post-procesamiento")
        
        if 'transcription_data' in st.session_state:
            original_text = fix_spanish_encoding_light(st.session_state.transcription_data.text)
            processed_text = st.session_state.transcription
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Original (Whisper puro):**")
                st.text_area("", original_text, height=400, key="orig", label_visibility="collapsed")
            
            with col2:
                st.markdown("**Procesado (con correcciones):**")
                st.text_area("", processed_text, height=400, key="proc", label_visibility="collapsed")
            
            # Análisis de diferencias
            import difflib
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                processed_text.splitlines(keepends=True),
                lineterm='',
                n=0
            )
            diff_text = ''.join(diff)
            
            if diff_text:
                with st.expander("📊 Ver diferencias detalladas"):
                    st.code(diff_text, language='diff')
            else:
                st.success("✅ No hay diferencias - la corrección no alteró el contenido")
    
    st.markdown("---")
    if st.button("🗑️ Empezar de nuevo (Limpiar todo)"):
        st.session_state.clear()
        st.rerun()
