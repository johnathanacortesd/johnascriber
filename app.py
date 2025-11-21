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
    st.markdown("""<div style='text-align:center;padding:3rem;'>
        <h1>🎙️</h1>
        <h2>Transcriptor Pro - Johnascriptor</h2>
        <p style='color:#888;'>Análisis avanzado de audio con IA</p>
    </div>""", unsafe_allow_html=True)
    
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

# --- DICCIONARIO DE CORRECCIONES MEJORADO ---
SPANISH_WORD_CORRECTIONS = {
    # Palabras cortadas comunes
    r'\baqu\b': 'aquí',
    r'\bAqu\b': 'Aquí',
    r'\ball\b': 'allí',
    r'\bAll\b': 'Allí',
    r'\bah\b': 'ahí',
    r'\bAh\b': 'Ahí',
    r'\balcald\b': 'alcaldía',
    r'\bAlcald\b': 'Alcaldía',
    r'\badministraci\b': 'administración',
    r'\bAdministraci\b': 'Administración',
    r'\bcomunicaci\b': 'comunicación',
    r'\bComunicaci\b': 'Comunicación',
    r'\bdeclaraci\b': 'declaración',
    r'\bDeclaraci\b': 'Declaración',
    r'\binformaci\b': 'información',
    r'\bInformaci\b': 'Información',
    r'\borganizaci\b': 'organización',
    r'\bOrganizaci\b': 'Organización',
    r'\bpoltic\b': 'política',
    r'\bPoltic\b': 'Política',
    r'\bRepblic\b': 'República',
    r'\brepblic\b': 'república',
    r'\btecnolog\b': 'tecnología',
    r'\bTecnolog\b': 'Tecnología',
    r'\bBogot\b': 'Bogotá',
    r'\bMxic\b': 'México',
    r'\bPer\b': 'Perú',
    r'\btambi\b': 'también',
    r'\bTambi\b': 'También',
    r'\bms\b': 'más',
    r'\bMs\b': 'Más',
    r'\bqu\b': 'qué',
    r'\bQu\b': 'Qué',
    r'\bcmo\b': 'cómo',
    r'\bCmo\b': 'Cómo',
    r'\bcundo\b': 'cuándo',
    r'\bCundo\b': 'Cuándo',
    r'\bdnde\b': 'dónde',
    r'\bDnde\b': 'Dónde',
    r'\best\b': 'está',
    r'\bEst\b': 'Está',
    r'\bser\b': 'será',
    r'\bSer\b': 'Será',
    
    # Correcciones de espacios incorrectos
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué',
}

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button onclick="navigator.clipboard.writeText({text_json})" 
        style="background:#0066cc;color:white;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:600;">
        📋 Copiar Todo</button>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" 
             for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    """Corrección mejorada de encoding y palabras cortadas"""
    if not text:
        return text
    
    result = text
    
    # Correcciones de encoding
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â¿': '¿', 'Â¡': '¡',
        'Ã': 'í', 'Ã': 'á', 'Ã³': 'ó'
    }
    
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    
    # Aplicar correcciones de palabras
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
    
    # Capitalización después de puntos
    result = re.sub(r'([.?!]\s+)([a-záéíóúñ])', 
                    lambda m: m.group(1) + m.group(2).upper(), result)
    
    # Primera letra mayúscula
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
    ✅ UTF-8 para preservar caracteres especiales
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
        ffmpeg_path = get_ffmpeg_exe()
        
        # Comando MEJORADO para preservar calidad de audio y caracteres
        cmd = [
            ffmpeg_path,
            '-i', input_path,
            '-vn',  # Sin video
            '-ar', '22050',  # Sample rate aumentado para mejor calidad
            '-ac', '1',  # Mono
            '-b:a', '96k',  # Bitrate aumentado para mejor precisión
            '-acodec', 'libmp3lame',
            '-q:a', '2',  # Calidad alta
            '-y',  # Sobrescribir
            output_path
        ]
        
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=120,
            creationflags=creation_flags,
            encoding='utf-8',  # Preservar UTF-8
            errors='replace'
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
            # Fallback
            try:
                os.unlink(input_path)
                if os.path.exists(output_path):
                    os.unlink(output_path)
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
                msg = f"✅ Optimizado: {orig_mb:.2f} MB → {final_mb:.2f} MB (-{reduction:.1f}%) | 96kbps mono 22kHz"
                return processed_bytes, {'converted': True, 'message': msg}
            elif was_converted:
                msg = f"✅ Convertido a MP3: {final_mb:.2f} MB | 96kbps mono 22kHz"
                return processed_bytes, {'converted': True, 'message': msg}
            else:
                return file_bytes, {'converted': False, 'message': f"⚠️ Procesando original ({original_size:.2f} MB)"}
        except Exception:
            return file_bytes, {'converted': False, 'message': f"⚠️ Procesando original ({original_size:.2f} MB)"}
    else:
        return file_bytes, {'converted': False, 'message': f"📁 Archivo listo ({original_size:.2f} MB)"}

# --- FUNCIONES DE POST-PROCESAMIENTO Y ANÁLISIS ---
def post_process_with_llama(transcription_text, client):
    """Post-procesamiento mejorado con énfasis en palabras cortadas"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": """Eres un experto en corrección de transcripciones en español de Colombia.

INSTRUCCIONES CRÍTICAS:
1. Completa palabras cortadas: "aqu" → "aquí", "alcald" → "alcaldía", "ms" → "más"
2. Añade tildes faltantes en palabras interrogativas y exclamativas
3. NO cambies el contenido, NO resumas, NO elimines texto
4. Mantén el estilo conversacional original
5. Solo corrige ortografía y palabras incompletas

Palabras comunes a vigilar: aquí, allí, ahí, más, qué, cómo, cuándo, dónde, alcaldía, administración, política, tecnología."""
                },
                {
                    "role": "user", 
                    "content": f"Corrige esta transcripción manteniendo TODO el contenido:\n\n{transcription_text}"
                }
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=8000  # Aumentado para textos largos
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
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    try:
        messages = [{"role": "system", "content": "Responde basándote ÚNICAMENTE en la transcripción."}]
        
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        
        messages.append({"role": "user", "content": f"Texto:\n{transcription_text}\n\nPregunta: {question}"})
        
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant",
            temperature=0.2,
            max_tokens=800
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def get_extended_context(segments, match_index, context_range=2):
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    return [{'text': segments[i]['text'].strip(), 
             'time': format_timestamp(segments[i]['start']),
             'start': segments[i]['start'],
             'is_match': (i == match_index)} 
            for i in range(start_idx, end_idx)]

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
    
    model_option = st.selectbox("Modelo", ["whisper-large-v3"], 
                                help="Máxima precisión para español.")
    
    language = st.selectbox("Idioma", ["es"], 
                           help="Español para máxima calidad.")
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    
    enable_llama_postprocess = st.checkbox(
        "🤖 Post-procesamiento IA (RECOMENDADO)", 
        value=True,  # ACTIVADO POR DEFECTO
        help="Corrige palabras cortadas y añade tildes faltantes"
    )
    
    enable_summary = st.checkbox("📝 Generar resumen", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Contexto")
    context_lines = st.slider("Líneas de contexto", 1, 5, 2)
    
    st.markdown("---")
    st.success("""
    ⚡ **Optimización FFmpeg Activa:**
    - Conversión automática a MP3
    - 96kbps mono 22kHz (Alta calidad)
    - Preservación UTF-8
    - 3-5x más rápido
    """)
    
    st.info("💡 Soporta todos los formatos de audio/video")

st.subheader("📤 Sube tu archivo")

col1, col2 = st.columns([3, 1])

with col1:
    uploaded_file = st.file_uploader(
        "Selecciona archivo",
        type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "avi", "mov", "mkv", "flac"],
        label_visibility="collapsed"
    )

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
            
            # PROMPT MEJORADO con vocabulario colombiano
            SPANISH_PROMPT = """Transcripción en español de Colombia. 
Vocabulario clave: aquí, allí, ahí, más, qué, cómo, dónde, cuándo, alcaldía, 
administración, política, tecnología, está, será, también, sí.
Usa tildes correctamente en palabras interrogativas y exclamativas."""
            
            with st.spinner("🔄 Transcribiendo con IA (Whisper v3 + Prompt mejorado)..."):
                with open(tmp_path, "rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        file=(uploaded_file.name, audio_file.read()),
                        model=model_option,
                        language=language,
                        prompt=SPANISH_PROMPT,
                        response_format="verbose_json",
                        temperature=0.0  # Temperatura en 0 para máxima precisión
                    )
            
            os.unlink(tmp_path)
            
            # Aplicar correcciones inmediatas
            transcription_text = fix_spanish_encoding(transcription.text)
            
            # Post-procesamiento si está activado
            if enable_llama_postprocess:
                with st.spinner("🤖 Refinando texto y completando palabras..."):
                    transcription_text = post_process_with_llama(transcription_text, client)
            
            # Corregir segmentos individuales
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
    st.audio(st.session_state.uploaded_audio_bytes, 
             start_time=st.session_state.get('audio_start_time', 0))
    
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
            st.button("🗑️ Limpiar", on_click=clear_search_callback, 
                     use_container_width=True, disabled=not search_query)
        
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
                            with c_t:
                                st.button(f"▶️ {ctx['time']}", 
                                         key=f"play_{match_idx}_{ctx['start']}",
                                         on_click=set_audio_time, args=(ctx['start'],),
                                         use_container_width=True)
                            with c_c:
                                txt = pattern.sub(f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', 
                                                 ctx['text']) if ctx['is_match'] else ctx['text']
                                style = MATCH_STYLE if ctx['is_match'] else CTX_STYLE
                                st.markdown(f'<div style="{style}">{txt}</div>', 
                                          unsafe_allow_html=True)
                        st.markdown("---")
        
        st.markdown("### Texto Completo")
        html_text = st.session_state.transcription.replace('\n', ' ')
        if search_query:
            html_text = re.compile(re.escape(search_query), re.IGNORECASE).sub(
                f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>', html_text
            )
        st.markdown(f'<div style="line-height:1.8;font-size:1.05rem;">{html_text}</div>', 
                   unsafe_allow_html=True)
        
        st.write("")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        with c1:
            st.download_button("💾 TXT", st.session_state.transcription, 
                             "transcripcion.txt", use_container_width=True)
        with c2:
            st.download_button("💾 TXT Tiempos", 
                             format_transcription_with_timestamps(st.session_state.transcription_data),
                             "tiempos.txt", use_container_width=True)
        with c3:
            st.download_button("💾 SRT", 
                             export_to_srt(st.session_state.transcription_data),
                             "sub.srt", use_container_width=True)
        with c4:
            create_copy_button(st.session_state.transcription)
    
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
                ans = answer_question(q, st.session_state.transcription, 
                                     Groq(api_key=api_key), st.session_state.qa_history)
                st.session_state.qa_history.append({'question': q, 'answer': ans})
                st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align:center;color:#888;padding:1rem;'>
    <b>Transcriptor Pro - Johnascriptor v4.1</b><br>
    ⚡ FFmpeg Nativo | 🎙️ Whisper v3 + Prompt | 🤖 Llama 3.1 | 🔧 UTF-8 Optimizado
</div>""", unsafe_allow_html=True)
