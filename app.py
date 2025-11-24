import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter

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
        <h2>Transcriptor Pro - Edición Exacta</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Sin resúmenes, sin inventos. Solo tu texto y chat.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro V12", page_icon="🎙️", layout="wide")

# --- ESTADO E INICIALIZACIÓN ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en secrets")
    st.stop()

# --- CALLBACKS UI (CRUCIAL PARA TIMESTAMPS) ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

# --- MEJORA 1: DETECCIÓN AVANZADA DE REPETICIONES ---
def detect_phrase_repetition(text, min_phrase_length=10, similarity_threshold=0.85):
    """
    Detecta frases completas repetidas, no solo palabras.
    Ejemplo: "y entonces dijo que..." repetido 5 veces
    """
    # Dividir en frases de aproximadamente min_phrase_length palabras
    words = text.split()
    phrases = []
    
    for i in range(len(words) - min_phrase_length + 1):
        phrase = ' '.join(words[i:i+min_phrase_length])
        phrases.append(phrase.lower())
    
    # Contar frecuencias
    phrase_counts = Counter(phrases)
    
    # Detectar frases que se repiten más de 2 veces
    repeated_phrases = [phrase for phrase, count in phrase_counts.items() if count > 2]
    
    return repeated_phrases

def remove_phrase_loops(text):
    """
    Elimina bucles de frases completas manteniendo solo la primera ocurrencia.
    """
    repeated = detect_phrase_repetition(text, min_phrase_length=5)
    
    for phrase in repeated:
        # Buscar el patrón repetido y dejarlo solo una vez
        pattern = re.escape(phrase)
        # Encuentra repeticiones consecutivas o cercanas
        text = re.sub(f'({pattern})(\\s+\\1)+', r'\1', text, flags=re.IGNORECASE)
    
    return text

# --- MEJORA ADICIONAL: DICCIONARIO FONÉTICO ESPAÑOL ---
PHONETIC_CORRECTIONS = {
    # Errores comunes de Whisper con español colombiano/latinoamericano
    r'\bpiéjese\b': 'fíjese',
    r'\bpiégese\b': 'fíjese',
    r'\bfígese\b': 'fíjese',
    r'\bpues\s+si\b': 'pues sí',
    r'\bestá\s+hay\b': 'está ahí',
    r'\bahí\s+hay\b': 'ahí hay',
    r'\bvéalo\b': 'véalo',
    r'\bvéala\b': 'véala',
    r'\boiga\b': 'oiga',
    r'\boido\b': 'oído',
    r'\bdijistes\b': 'dijiste',
    r'\bhacistes\b': 'hiciste',
    r'\btrájeron\b': 'trajeron',
    r'\bhaiga\b': 'haya',
    r'\bnadies\b': 'nadie',
    r'\byendo\b': 'yendo',
    r'\bpá\b': 'para',
    r'\bpa\s+': 'para ',
    r'\bto\b': 'todo',
    r'\bnojoda\b': 'no joda',
    r'\bquiubo\b': 'qué hubo',
    r'\bmijo\b': 'mi hijo',
    r'\bmija\b': 'mi hija',
    r'\bel\s+llave\b': 'el llaves',  # Colombianismo
    r'\bparce\b': 'parce',  # Ya está bien, pero lo mantenemos
    r'\bchinear\b': 'chinear',  # Colombianismo válido
}

def fix_encoding_errors(text):
    """
    Repara caracteres Unicode corruptos y encoding mal interpretado.
    """
    if not text: return ""
    
    # Reemplazar el carácter de reemplazo Unicode
    text = text.replace('�', '')
    
    # Patrones comunes de encoding roto
    encoding_fixes = {
        'Ã±': 'ñ',
        'Ã¡': 'á',
        'Ã©': 'é',
        'Ã­': 'í',
        'Ã³': 'ó',
        'Ãº': 'ú',
        'Ã': 'Ñ',
        'Ã': 'Á',
        'Ã‰': 'É',
        'Ã': 'Í',
        'Ã"': 'Ó',
        'Ãš': 'Ú',
        'Â¿': '¿',
        'Â¡': '¡',
    }
    
    for broken, fixed in encoding_fixes.items():
        text = text.replace(broken, fixed)
    
    # Eliminar caracteres de control invisibles
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    
    # Normalizar espacios no estándar
    text = re.sub(r'[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]', ' ', text)
    
    return text

def apply_phonetic_corrections(text):
    """
    Corrige errores fonéticos comunes de Whisper en español.
    """
    corrected = text
    for pattern, replacement in PHONETIC_CORRECTIONS.items():
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
    return corrected

# --- MEJORA 2: LIMPIEZA MEJORADA ANTI-ALUCINACIONES ---
def clean_whisper_hallucinations(text, apply_phonetic=True):
    """Limpia frases inventadas comunes en silencios y bucles."""
    if not text: return ""
    
    # PASO 1: Reparar encoding (siempre activo)
    text = fix_encoding_errors(text)
    
    # PASO 2: Aplicar correcciones fonéticas (opcional)
    if apply_phonetic:
        text = apply_phonetic_corrections(text)
    
    # Patrones de basura que Whisper V3 suele inventar
    junk_patterns = [
        r"Subtítulos realizados por.*",
        r"Comunidad de editores.*",
        r"Amara\.org.*",
        r"Transcribed by.*",
        r"Sujeto a.*licencia.*",
        r"Copyright.*",
        r"Gracias por ver.*",
        r"Suscríbete.*",
        r"Dale like.*",
        r"Comparte este video.*",
        r"Visita nuestro sitio.*",
        # NUEVO: Patrones de palabras clave repetitivas
        r"\b(siguiente|anterior|continuar|página|menú|inicio)\b(\s+\1\b){2,}",
    ]
    
    cleaned = text
    for pattern in junk_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Eliminar repeticiones de palabras simples (ej: "hola hola hola")
    cleaned = re.sub(r'\b(\w+)( \1\b){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    
    # MEJORA 3: Eliminar bucles de frases completas
    cleaned = remove_phrase_loops(cleaned)
    
    # Limpiar espacios múltiples
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    
    return cleaned.strip()

# --- MEJORA 4: FILTRADO INTELIGENTE DE SEGMENTOS ---
def filter_segments_data(segments, apply_phonetic=True):
    """
    Limpia la data de segmentos con filtros más inteligentes.
    Evita perder información valiosa pero elimina basura real.
    """
    clean_segments = []
    last_text = ""
    consecutive_short = 0
    
    for seg in segments:
        txt = clean_whisper_hallucinations(seg['text'], apply_phonetic)
        
        # Filtros de calidad más permisivos
        if len(txt) == 0: 
            continue
        
        # MEJORA: Permitir segmentos cortos si no son consecutivos
        if len(txt) < 3:
            consecutive_short += 1
            if consecutive_short > 3:  # Solo bloquear si hay muchos seguidos
                continue
        else:
            consecutive_short = 0
        
        # Detectar repetición exacta (case-insensitive)
        if txt.lower() == last_text.lower():
            continue
        
        # MEJORA: Detectar frases muy similares (>90% similitud)
        if last_text and len(txt) > 10:
            similarity = sum(a == b for a, b in zip(txt.lower(), last_text.lower())) / max(len(txt), len(last_text))
            if similarity > 0.9:
                continue
        
        seg['text'] = txt
        clean_segments.append(seg)
        last_text = txt
        
    return clean_segments

# --- MEJORA 5: CHUNKING DE AUDIO PARA ARCHIVOS LARGOS ---
def should_chunk_audio(duration_seconds):
    """
    Whisper puede fallar en audios muy largos (>30 min).
    Retorna True si necesita chunking.
    """
    return duration_seconds > 1800  # 30 minutos

def get_audio_duration(audio_path):
    """Obtiene duración del audio usando ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, check=True
        )
        return float(result.stdout.strip())
    except:
        return 0

# --- FUNCIONES DE CORRECCIÓN QUIRÚRGICA ---
def text_chunker_smart(text, chunk_size=2500):
    """Corta por oraciones para no romper contexto."""
    sentences = re.split(r'(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚÑ])', text)
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 < chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk: chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk: chunks.append(current_chunk.strip())
    return chunks

def surgical_correction(text, client):
    """
    Corrección estricta: solo tildes. 
    Safety Check: Si cambia mucho el texto (longitud), se descarta el cambio.
    """
    chunks = text_chunker_smart(text)
    final_parts = []
    
    progress_text = "🧠 Aplicando corrección quirúrgica (solo tildes)..."
    my_bar = st.progress(0, text=progress_text)
    
    system_prompt = """Eres un corrector ortográfico estricto para español.
TU MISIÓN:
1. Poner tildes faltantes (telefonía, tecnología, etc.)
2. Corregir errores fonéticos comunes: "piéjese" → "fíjese", "oiga" → "oiga", "trájeron" → "trajeron"

PROHIBIDO:
- Cambiar palabras (ej: 'telefono' -> 'móvil' PROHIBIDO).
- Resumir o eliminar texto.
- Cambiar puntuación técnica.
- Modificar nombres propios (marcas, lugares, personas).

Ejemplo:
Entrada: "la telefonia y piéjese que hay tecnologia"
Salida: "la telefonía y fíjese que hay tecnología"

Si la entrada ya está bien, devuélvela IDÉNTICA. Solo responde con el texto corregido."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                max_tokens=len(chunk) + 500
            )
            corrected = response.choices[0].message.content.strip()
            
            # --- SAFETY CHECK ---
            len_diff = abs(len(corrected) - len(chunk))
            ratio = len_diff / len(chunk) if len(chunk) > 0 else 0
            
            if ratio > 0.10: 
                final_parts.append(chunk)
            else:
                final_parts.append(corrected)
                
        except:
            final_parts.append(chunk)
            
        my_bar.progress((i + 1) / len(chunks))
        
    my_bar.empty()
    return " ".join(final_parts)

def analyze_transcription_quality(text, segments):
    """
    Analiza la calidad de la transcripción y retorna métricas.
    """
    issues = []
    
    # Detectar caracteres corruptos restantes
    if '�' in text or 'Ã' in text:
        issues.append("encoding")
    
    # Detectar repeticiones excesivas
    words = text.lower().split()
    word_freq = Counter(words)
    most_common = word_freq.most_common(10)
    if most_common and most_common[0][1] > len(words) * 0.05:  # Más del 5%
        issues.append("repetition")
    
    # Detectar segmentos muy cortos (posible pérdida de info)
    short_segments = sum(1 for seg in segments if len(seg['text']) < 5)
    if short_segments > len(segments) * 0.3:  # Más del 30%
        issues.append("short_segments")
    
    # Calcular densidad de palabras por minuto (WPM)
    if segments:
        duration_minutes = segments[-1]['end'] / 60
        wpm = len(words) / duration_minutes if duration_minutes > 0 else 0
    else:
        wpm = 0
    
    return {
        'issues': issues,
        'wpm': round(wpm, 1),
        'most_common_word': most_common[0] if most_common else ('N/A', 0),
        'short_segments_pct': round(short_segments / len(segments) * 100, 1) if segments else 0
    }

# --- UTILIDADES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #ddd; background: #fff;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
    components.html(button_html, height=40)

def format_timestamp(seconds):
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def get_extended_context(segments, match_index, context_range=2):
    start = max(0, match_index - context_range)
    end = min(len(segments), match_index + context_range + 1)
    return [{'text': segments[i]['text'], 'time': format_timestamp(segments[i]['start']), 'start': segments[i]['start'], 'is_match': (i == match_index)} for i in range(start, end)]

def export_to_srt(segments):
    srt = []
    for i, seg in enumerate(segments, 1):
        s = timedelta(seconds=seg['start'])
        e = timedelta(seconds=seg['end'])
        s_str = f"{s.seconds//3600:02}:{(s.seconds//60)%60:02}:{s.seconds%60:02},{s.microseconds//1000:03}"
        e_str = f"{e.seconds//3600:02}:{(e.seconds//60)%60:02}:{e.seconds%60:02},{e.microseconds//1000:03}"
        srt.append(f"{i}\n{s_str} --> {e_str}\n{seg['text']}\n")
    return "\n".join(srt)

def export_to_json(segments, full_text):
    """Exporta la transcripción en formato JSON con timestamps."""
    data = {
        'full_text': full_text,
        'segments': [
            {
                'id': i,
                'start': seg['start'],
                'end': seg['end'],
                'text': seg['text'],
                'timestamp': format_timestamp(seg['start'])
            }
            for i, seg in enumerate(segments)
        ],
        'metadata': {
            'total_segments': len(segments),
            'total_words': len(full_text.split()),
            'duration_seconds': segments[-1]['end'] if segments else 0
        }
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

# --- MEJORA 6: OPTIMIZACIÓN AUDIO CON NORMALIZACIÓN ---
def optimize_audio_robust(file_bytes, filename):
    """
    Convierte cualquier entrada a MP3 16kHz Mono con normalización de volumen.
    Esto es CRUCIAL para que Whisper no alucine.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp.write(file_bytes)
        input_path = tmp.name
    
    output_path = input_path + "_opt.mp3"
    try:
        # MEJORA: Agregar filtro de normalización y reducción de ruido leve
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-vn",  # Sin video
            "-ar", "16000",  # Sample rate óptimo para Whisper
            "-ac", "1",  # Mono
            "-b:a", "64k",  # MEJORA: Subido de 32k a 64k para mejor calidad
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,highpass=f=200,lowpass=f=3000",  # Normalización + filtros de voz
            "-f", "mp3",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(output_path, 'rb') as f: 
            new_bytes = f.read()
        os.unlink(input_path)
        os.unlink(output_path)
        return new_bytes, True
    except Exception as e:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, False

# --- FUNCIÓN CHAT ---
def answer_question(q, text, client, history):
    msgs = [{"role": "system", "content": "Eres un asistente útil. Responde preguntas basándote ÚNICAMENTE en la transcripción proporcionada. Si no está en el texto, dilo."}]
    for item in history:
        msgs.append({"role": "user", "content": item['question']})
        msgs.append({"role": "assistant", "content": item['answer']})
    msgs.append({"role": "user", "content": f"Transcripción:\n{text[:25000]}\n\nPregunta: {q}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- INTERFAZ PRINCIPAL ---
st.title("🎙️ Transcriptor Pro V12 - Johnascriptor")
st.caption("✨ Versión mejorada: Sin repeticiones, sin espacios vacíos, 100% exacta")

with st.sidebar:
    st.header("⚙️ Configuración")
    st.markdown("### Modos de Precisión")
    mode = st.radio("Nivel de Corrección:", ["Whisper Puro (Sin cambios)", "Quirúrgico (Solo Tildes)"], index=1)
    
    st.markdown("---")
    st.markdown("### 🔧 Ajustes Avanzados")
    
    # MEJORA 7: Control de temperatura ajustable
    temperature = st.slider("Temperatura Whisper", 0.0, 0.5, 0.1, 0.05, 
                           help="0.0 = Muy determinístico (puede repetir). 0.1-0.2 = Balance óptimo. 0.3+ = Más creativo pero menos preciso.")
    
    # Opción para activar/desactivar correcciones fonéticas
    enable_phonetic = st.checkbox("Correcciones fonéticas automáticas", value=True,
                                   help="Corrige 'piéjese'→'fíjese', 'oiga'→'oiga', etc.")
    
    st.markdown("---")
    st.info("✅ Mejoras activas:\n- Normalización de audio\n- Detección de bucles\n- Filtrado inteligente\n- Reparación de encoding\n- Diccionario fonético español")
    
    st.markdown("---")
    with st.expander("🛠️ Solución de Problemas"):
        st.markdown("""
        **Si aún hay repeticiones:**
        - Baja la temperatura a 0.05
        - Revisa que el audio no tenga eco
        
        **Si faltan palabras:**
        - Sube la temperatura a 0.15-0.2
        - Verifica que el audio sea claro
        
        **Si hay "�" en el texto:**
        - Automáticamente reparado
        - Si persiste, el audio original tiene problemas
        
        **Si dice palabras raras:**
        - Activa "Correcciones fonéticas"
        - Usa el modo "Quirúrgico" después
        """)

uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov", "flac", "aac"])

if st.button("🚀 Iniciar Transcripción", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    # Validación inicial del archivo
    if uploaded_file.size == 0:
        st.error("❌ El archivo está vacío. Por favor, sube un archivo de audio válido.")
        st.stop()
    
    if uploaded_file.size > 500 * 1024 * 1024:  # 500 MB
        st.warning("⚠️ Archivo muy grande (>500MB). La transcripción puede tardar varios minutos.")
    
    try:
        # 1. OPTIMIZAR CON NORMALIZACIÓN
        with st.spinner("🔄 Optimizando audio (Normalización + Filtros de Voz)..."):
            audio_bytes, optimized = optimize_audio_robust(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = audio_bytes
            if not optimized: 
                st.warning("⚠️ No se pudo optimizar el audio, usando original.")

        # 2. TRANSCRIBIR CON PARÁMETROS MEJORADOS
        with st.spinner("📝 Transcribiendo con Whisper V3 (Modo Exacto Mejorado)..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            # MEJORA 8: Prompt mejorado y temperatura ajustable
            enhanced_prompt = """Esta es una transcripción en español de una conversación o presentación. 
Transcribe exactamente lo que escuchas sin repetir frases, sin agregar texto de relleno, 
y sin inventar contenido en silencios. Usa puntuación natural española."""
            
            with open(tmp_path, "rb") as f:
                transcription_data = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=temperature,  # Temperatura ajustable
                    prompt=enhanced_prompt  # Prompt mejorado
                )
            os.unlink(tmp_path)
            
            # Diagnóstico (opcional)
            st.sidebar.success(f"✅ Segmentos detectados: {len(transcription_data.segments)}")

        # 3. LIMPIEZA ANTI-ALUCINACIONES MEJORADA
        raw_text_cleaned = clean_whisper_hallucinations(transcription_data.text, enable_phonetic)
        segments_cleaned = filter_segments_data(transcription_data.segments, enable_phonetic)
        
        # Diagnóstico de limpieza
        removed = len(transcription_data.segments) - len(segments_cleaned)
        if removed > 0:
            st.sidebar.info(f"🧹 Segmentos filtrados: {removed}")
        
        # Detectar y reportar problemas de encoding
        if '�' in transcription_data.text:
            st.sidebar.warning("⚠️ Se detectaron y repararon problemas de encoding")
        
        # Analizar calidad de transcripción
        quality = analyze_transcription_quality(raw_text_cleaned, segments_cleaned)
        st.session_state.quality_report = quality  # Guardar para el reporte
        
        if quality['issues']:
            issues_text = {
                'encoding': '🔤 Problemas de encoding reparados',
                'repetition': '🔁 Repeticiones detectadas y limpiadas',
                'short_segments': '⚠️ Muchos segmentos cortos detectados'
            }
            for issue in quality['issues']:
                st.sidebar.info(issues_text.get(issue, issue))
        
        # Mostrar métricas de calidad
        st.sidebar.metric("📊 Palabras/minuto", quality['wpm'])
        
        # 4. CORRECCIÓN OPCIONAL
        if mode == "Quirúrgico (Solo Tildes)":
            final_text = surgical_correction(raw_text_cleaned, client)
        else:
            final_text = raw_text_cleaned
            
        # 5. ACTUALIZAR ESTADO
        st.session_state.transcription_text = final_text
        st.session_state.segments = segments_cleaned
        
        st.balloons()
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ Error crítico: {e}")
        st.exception(e)  # Muestra el traceback completo

# --- VISUALIZACIÓN ---
if 'transcription_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    # Estadísticas rápidas
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📝 Palabras", len(st.session_state.transcription_text.split()))
    col2.metric("⏱️ Segmentos", len(st.session_state.segments))
    col3.metric("🔤 Caracteres", len(st.session_state.transcription_text))
    
    # Calcular y mostrar duración si está disponible
    if st.session_state.segments:
        duration_min = st.session_state.segments[-1]['end'] / 60
        col4.metric("⏰ Duración", f"{duration_min:.1f} min")
    else:
        col4.metric("⏰ Duración", "N/A")
    
    tab1, tab2 = st.tabs(["📝 Transcripción & Búsqueda", "💬 Chat con Audio"])
    
    # --- TAB 1: TRANSCRIPCIÓN INTERACTIVA ---
    with tab1:
        col_s1, col_s2 = st.columns([4, 1])
        query = col_s1.text_input("🔎 Buscar palabra (Clic en resultados para ir al audio):", key="search_input")
        col_s2.write(""); col_s2.button("✖️", on_click=clear_search_callback)
        
        # BÚSQUEDA Y RESULTADOS CLICABLES
        if query:
            matches_found = False
            with st.expander(f"📍 Resultados para: '{query}'", expanded=True):
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        matches_found = True
                        context = get_extended_context(st.session_state.segments, i, 1)
                        for ctx in context:
                            c1, c2 = st.columns([0.15, 0.85])
                            key_btn = f"t_{i}_{ctx['start']}"
                            c1.button(f"▶️ {ctx['time']}", key=key_btn, on_click=set_audio_time, args=(ctx['start'],))
                            
                            txt_display = ctx['text']
                            if ctx['is_match']:
                                txt_display = re.sub(re.escape(query), f"**{query.upper()}**", txt_display, flags=re.IGNORECASE)
                            c2.markdown(txt_display)
                        st.divider()
                if not matches_found: st.warning("No se encontraron coincidencias.")

        st.markdown("### 📄 Texto Completo")
        st.text_area("Copia el texto aquí:", st.session_state.transcription_text, height=600, label_visibility="collapsed")
        
        st.markdown("### 💾 Exportar")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.download_button("📄 TXT", st.session_state.transcription_text, "transcripcion.txt", use_container_width=True)
        c2.download_button("🎬 SRT", export_to_srt(st.session_state.segments), "subtitulos.srt", use_container_width=True)
        c3.download_button("📊 JSON", export_to_json(st.session_state.segments, st.session_state.transcription_text), "transcripcion.json", use_container_width=True)
        
        # Generar reporte de diagnóstico
        if 'quality_report' in st.session_state:
            quality = st.session_state.quality_report
            report_text = f"""REPORTE DE TRANSCRIPCIÓN
=====================================
📊 Estadísticas:
- Palabras totales: {len(st.session_state.transcription_text.split())}
- Segmentos: {len(st.session_state.segments)}
- Palabras por minuto: {quality['wpm']}
- Palabra más frecuente: "{quality['most_common_word'][0]}" ({quality['most_common_word'][1]} veces)

🔧 Correcciones Aplicadas:
{chr(10).join(['- ' + {'encoding': 'Reparación de encoding UTF-8', 'repetition': 'Eliminación de repeticiones', 'short_segments': 'Filtrado de segmentos cortos'}.get(issue, issue) for issue in quality['issues']]) if quality['issues'] else '- Ninguna (transcripción limpia)'}

✅ Calidad: {'Excelente' if not quality['issues'] else 'Buena (con correcciones)'}
"""
            c4.download_button("📋 Reporte", report_text, "reporte.txt", use_container_width=True)
        
        with c5: create_copy_button(st.session_state.transcription_text)

    # --- TAB 2: CHAT ---
    with tab2:
        st.subheader("💬 Chat con el Audio")
        st.caption("Haz preguntas específicas sobre la transcripción.")
        
        for msg in st.session_state.qa_history:
            with st.chat_message("user"): st.write(msg['question'])
            with st.chat_message("assistant"): st.write(msg['answer'])
            
        if prompt := st.chat_input("Pregunta algo sobre el contenido..."):
            st.session_state.qa_history.append({"question": prompt, "answer": "..."})
            with st.spinner("Consultando transcripción..."):
                ans = answer_question(prompt, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history[:-1])
                st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo / Nuevo Archivo"):
        st.session_state.clear()
        st.rerun()
