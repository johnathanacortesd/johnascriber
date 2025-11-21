import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
from imageio_ffmpeg import get_ffmpeg_exe

# --- LÓGICA DE AUTENTICACIÓN ROBUSTA ---
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
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    st.stop()

# --- INICIO DE LA APP PRINCIPAL ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- INICIALIZACIÓN DE ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []

# --- FUNCIONES CALLBACK ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    r'\badministraci(?!ón\b)\b': 'administración', r'\bAdministraci(?!ón\b)\b': 'Administración',
    r'\bcomunicaci(?!ón\b)\b': 'comunicación', r'\bComunicaci(?!ón\b)\b': 'Comunicación',
    r'\bdeclaraci(?!ón\b)\b': 'declaración', r'\bDeclaraci(?!ón\b)\b': 'Declaración',
    r'\binformaci(?!ón\b)\b': 'información', r'\bInformaci(?!ón\b)\b': 'Información',
    r'\borganizaci(?!ón\b)\b': 'organización', r'\bOrganizaci(?!ón\b)\b': 'Organización',
    r'\bpolític(?!a\b)\b': 'política', r'\bPolític(?!a\b)\b': 'Política',
    r'\bRepúblic(?!a\b)\b': 'República', r'\brepúblic(?!a\b)\b': 'república',
    r'\btecnolog(?!ía\b)\b': 'tecnología', r'\bTecnolog(?!ía\b)\b': 'Tecnología',
    r'\bBogot(?!á\b)\b': 'Bogotá', r'\bMéxic(?!o\b)\b': 'México', r'\bPer\b': 'Perú',
    r'\btambi(?!én\b)\b': 'también', r'\bTambi(?!én\b)\b': 'También',
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué',
    r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde',
    r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const textArea = document.createElement("textarea");textArea.value = {text_json};textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";document.body.appendChild(textArea);textArea.select();document.execCommand("copy");document.body.removeChild(textArea);const button = document.getElementById("{button_id}");const originalText = button.innerText;button.innerText = "✅ ¡Copiado!";setTimeout(function() {{ button.innerText = originalText; }}, 2000);}};
</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â\u00bf': '\u00bf', 'Â\u00a1': '\u00a1'
    }
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', lambda m: m.group(1) + m.group(2).upper(), result)
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result.strip()

# --- FUNCIONES DE CONVERSIÓN OPTIMIZADA (FFmpeg Nativo) ---
def get_file_size_mb(file_bytes):
    return len(file_bytes) / (1024 * 1024)

def convert_to_optimized_mp3(file_bytes, filename):
    """
    Conversión ultra-rápida con FFmpeg embebido
    ✅ Sin dependencias externas pesadas
    ✅ 3-5x más rápido que MoviePy
    """
    try:
        original_size = get_file_size_mb(file_bytes)
        file_ext = os.path.splitext(filename)[1].lower()
        
        # No convertir MP3 pequeños ya optimizados
        if file_ext == '.mp3' and original_size < 8:
            return file_bytes, False, original_size, original_size
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
            tmp_input.write(file_bytes)
            input_path = tmp_input.name
        
        output_path = input_path.rsplit('.', 1)[0] + '_optimized.mp3'
        
        # Obtener FFmpeg del paquete imageio-ffmpeg
        ffmpeg_path = get_ffmpeg_exe()
        
        # Comando optimizado para voz (64kbps mono 16kHz)
        cmd = [
            ffmpeg_path, '-i', input_path,
            '-vn',          # Sin video
            '-ar', '16000', # Sample rate óptimo para Whisper
            '-ac', '1',     # Mono
            '-b:a', '64k',  # Bitrate óptimo para voz
            '-y',           # Sobrescribir
            output_path
        ]
        
        # Ejecutar FFmpeg silenciando la salida
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=120,
            creationflags=creation_flags
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                mp3_bytes = f.read()
            
            final_size = get_file_size_mb(mp3_bytes)
            
            # Limpieza
            try:
                os.unlink(input_path)
                os.unlink(output_path)
            except:
                pass
            
            return mp3_bytes, True, original_size, final_size
        else:
            # Fallback: Limpiar y devolver original
            try:
                os.unlink(input_path)
                if os.path.exists(output_path): os.unlink(output_path)
            except:
                pass
            return file_bytes, False, original_size, original_size
            
    except Exception:
        return file_bytes, False, original_size, original_size

def process_audio_for_transcription(uploaded_file):
    """Procesa y optimiza archivos para transcripción"""
    file_bytes = uploaded_file.getvalue()
    original_size = get_file_size_mb(file_bytes)
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    
    should_convert = (file_ext != '.mp3' or original_size > 8)
    
    if should_convert:
        try:
            processed_bytes, was_converted, orig_mb, final_mb = convert_to_optimized_mp3(
                file_bytes, uploaded_file.name
            )
            if was_converted and final_mb < orig_mb:
                reduction = ((orig_mb - final_mb) / orig_mb * 100) if orig_mb > 0 else 0
                msg = f"✅ Optimizado: {orig_mb:.2f} MB → {final_mb:.2f} MB (-{reduction:.1f}%) | 64kbps mono 16kHz"
                return processed_bytes, {'converted': True, 'message': msg}
            elif was_converted:
                msg = f"✅ Convertido a MP3: {final_mb:.2f} MB | 64kbps mono 16kHz"
                return processed_bytes, {'converted': True, 'message': msg}
            else:
                return file_bytes, {'converted': False, 'message': f"⚠️ Procesando original ({original_size:.2f} MB)"}
        except Exception:
            return file_bytes, {'converted': False, 'message': f"⚠️ Procesando original ({original_size:.2f} MB)"}
    else:
        return file_bytes, {'converted': False, 'message': f"📁 Archivo listo ({original_size:.2f} MB)"}

# --- FUNCIONES DE POST-PROCESAMIENTO Y ANÁLISIS ---
def post_process_with_llama(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Tu tarea es añadir tildes faltantes al texto en español. NO cambies palabras, NO resumas, NO elimines nada. Solo ortografía."},
                {"role": "user", "content": f"Corrige ortografía:\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.1, max_tokens=4096
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception:
        return transcription_text

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un asistente experto. Crea resúmenes ejecutivos concisos en español."},
                {"role": "user", "content": f"Resumen ejecutivo (max 150 palabras):\n\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción."}]
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": f"Texto:\n{transcription_text}\n\nPregunta: {question}"})
        chat_completion = client.chat.completions.create(
            messages=messages, model="llama-3.1-8b-instant", temperature=0.2, max_tokens=800
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
        start_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt_content.append(f"{i}\n{start_str} --> {end_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt_content)

# --- INTERFAZ ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"], help="Máxima precisión para español.")
    language = st.selectbox("Idioma", ["es"], help="Español para máxima calidad.")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_llama_postprocess = st.checkbox("🤖 Post-procesamiento IA (opcional)", value=False, help="Raramente necesario con el nuevo prompt.")
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Contexto")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    
    st.markdown("---")
    st.success("""
    ⚡ **Optimización FFmpeg Activa:**
    - Conversión automática a MP3
    - 64kbps mono 16kHz (Voz)
    - 3-5x más rápido
    """)
    st.info("💡 Soporta todos los formatos de audio/video")

st.subheader("📤 Sube tu archivo")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Selecciona archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "avi", "mov", "mkv", "flac"], label_visibility="collapsed")
with col2:
    if st.button("🚀 Iniciar", type="primary", use_container_width=True, disabled=not uploaded_file):
        st.session_state.clear()
        st.session_state.password_correct = True 
        st.session_state.qa_history = []
        
        try:
            with st.spinner("🔄 Optimizando audio (FFmpeg nativo)..."):
                file_bytes, conversion_info = process_audio_for_transcription(uploaded_file)
                st.info(conversion_info['message'])

            st.session_state.uploaded_audio_bytes = file_bytes
            client = Groq(api_key=api_key)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # Prompt inteligente para tildes y puntuación
            SPANISH_PROMPT = "Transcripción en español de Colombia. Palabras clave: más, qué, cómo, dónde, cuándo, sí, está, administración, política."

            with st.spinner("🔄 Transcribiendo con IA (Whisper v3 + Prompt)..."):
                with open(tmp_path, "rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        file=(uploaded_file.name, audio_file.read()), 
                        model=model_option, 
                        language=language,
                        prompt=SPANISH_PROMPT,
                        response_format="verbose_json",
                        temperature=0.1
                    )
            os.unlink(tmp_path)
            
            transcription_text = fix_spanish_encoding(transcription.text)
            if enable_llama_postprocess:
                with st.spinner("🤖 Refinando texto..."):
                    transcription_text = post_process_with_llama(transcription_text, client)
            
            for seg in transcription.segments:
                seg['text'] = fix_spanish_encoding(seg['text'])
            
            st.session_state.transcription = transcription_text
            st.session_state.transcription_data = transcription
            
            if enable_summary:
                with st.spinner("🧠 Generando resumen..."):
                    st.session_state.summary = generate_summary(transcription_text, client)
            
            st.success("✅ ¡Proceso completado!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error: {e}")

if 'transcription' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.get('audio_start_time', 0))
    
    tabs = st.tabs(["📝 Transcripción", "📊 Resumen", "💬 Chat"])
    
    # TAB 1: Transcripción
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;"
        MATCH_STYLE = "background-color:#1e3a5f;padding:0.8rem;border-radius:6px;border-left:4px solid #fca311;color:#ffffff;"
        CTX_STYLE = "background-color:#1a1a1a;padding:0.6rem;border-radius:4px;color:#b8b8b8;"
        
        col_s1, col_s2 = st.columns([4, 1])
        with col_s1: 
            search_query = st.text_input("🔎 Buscar:", key="search_input")
        with col_s2: 
            st.write("")
            st.button("🗑️ Limpiar", on_click=clear_search_callback, use_container_width=True, disabled=not search_query)

        if search_query:
            with st.expander("📍 Resultados", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matches = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                
                if matches:
                    st.success(f"✅ {len(matches)} coincidencias.")
                    for match_idx in matches:
                        for ctx in get_extended_context(segments, match_idx, context_lines):
                            c_t, c_c = st.columns([0.15, 0.85])
                            with c_t: st.button(f"▶️ {ctx['time']}", key=f"play_{match_idx}_{ctx['start']}", on_click=set_audio_time, args=(ctx['start'],), use_container_width=True)
                            with c_c:
                                txt = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', ctx['text']) if ctx['is_match'] else ctx['text']
                                style = MATCH_STYLE if ctx['is_match'] else CTX_STYLE
                                st.markdown(f"<div style='{style}'>{txt}</div>", unsafe_allow_html=True)
                        st.markdown("---")
        
        st.markdown("### Texto Completo")
        html_text = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            html_text = re.compile(re.escape(search_query), re.IGNORECASE).sub(f'<span style="{HIGHLIGHT_STYLE}">\g<0></span>', html_text)
        
        st.markdown(f'<div style="background-color:#0E1117;color:#FAFAFA;padding:1.5rem;border-radius:10px;max-height:500px;overflow-y:auto;border:1px solid #333;">{html_text}</div>', unsafe_allow_html=True)
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        with c1: st.download_button("💾 TXT", st.session_state.transcription, "transcripcion.txt", use_container_width=True)
        with c2: st.download_button("💾 TXT Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data), "tiempos.txt", use_container_width=True)
        with c3: st.download_button("💾 SRT", export_to_srt(st.session_state.transcription_data), "sub.srt", use_container_width=True)
        with c4: create_copy_button(st.session_state.transcription)

    # TAB 2: Resumen
    with tabs[1]:
        st.markdown("### 📝 Resumen Ejecutivo")
        if st.session_state.get('summary'):
            st.info(st.session_state.summary)
        else:
            st.warning("Resumen no disponible o no activado.")

    # TAB 3: Chat
    with tabs[2]:
        st.markdown("### 💬 Chat con el Audio")
        for qa in st.session_state.qa_history:
            st.markdown(f"**❓ {qa['question']}**")
            st.markdown(f"💡 {qa['answer']}")
            st.markdown("---")
        
        with st.form("qa_form"):
            q = st.text_area("Pregunta:", height=80)
            if st.form_submit_button("Enviar") and q:
                ans = answer_question(q, st.session_state.transcription, Groq(api_key=api_key), st.session_state.qa_history)
                st.session_state.qa_history.append({'question': q, 'answer': ans})
                st.rerun()

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; font-size: 0.8rem;'>
    <b>Transcriptor Pro - Johnascriptor v4.0</b><br>
    ⚡ FFmpeg Nativo | 🎙️ Whisper v3 + Prompt | 🤖 Llama 3.1
</div>
""", unsafe_allow_html=True)
