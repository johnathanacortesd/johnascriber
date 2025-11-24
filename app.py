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
        <h2>Transcriptor Pro V14 - Fixed Edition</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Audio limpio. Transcripción exacta.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Pro V14", page_icon="🎙️", layout="wide")

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

# --- 1. OPTIMIZACIÓN DE AUDIO (CORREGIDA) ---
def optimize_audio_safe(file_bytes, filename):
    """
    CORRECCIÓN: Se eliminaron los filtros highpass/lowpass que destruían la voz.
    Solo se aplica normalización de volumen y conversión a mono 16kHz.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp.write(file_bytes)
        input_path = tmp.name
    
    output_path = input_path + "_opt.mp3"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-vn",          # Sin video
            "-ar", "16000", # Sample rate nativo Whisper
            "-ac", "1",     # Mono
            "-b:a", "96k",  # Bitrate alto para mantener calidad
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", # Solo normalizar volumen
            "-f", "mp3",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(output_path, 'rb') as f: 
            new_bytes = f.read()
        
        try:
            os.unlink(input_path)
            os.unlink(output_path)
        except: pass
            
        return new_bytes, True
    except Exception as e:
        # Fallback silencioso al original si falla ffmpeg
        if os.path.exists(input_path): 
            try: os.unlink(input_path)
            except: pass
        return file_bytes, False

# --- 2. LIMPIEZA DE ALUCINACIONES ---
def clean_whisper_hallucinations(text):
    if not text: return ""
    
    # Patrones basura conocidos
    junk_patterns = [
        r"Subtítulos realizados por.*",
        r"Comunidad de editores.*",
        r"Amara\.org.*",
        r"Transcribed by.*",
        r"Sujeto a.*licencia.*",
        r"Copyright.*",
        r"\[Música\]",
        r"\[Aplausos\]",
        r"\[Risas\]",
        r"Suscríbete.*",
        r"Dale like.*",
        # El patrón que causó el error anterior (por si acaso vuelve)
        r"No inventar texto\.",
        r"Transcripción verbatim\."
    ]
    
    cleaned = text
    for pattern in junk_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Eliminar repeticiones consecutivas de palabras (hola hola)
    cleaned = re.sub(r'\b(\w+)( \1\b)+', r'\1', cleaned, flags=re.IGNORECASE)
    
    # Eliminar espacios múltiples
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    
    return cleaned.strip()

# --- 3. FILTRADO DE SEGMENTOS ---
def filter_segments_data(segments):
    """Reconstruye el texto evitando segmentos vacíos o basura pura."""
    clean_segments = []
    full_text_parts = []
    
    for seg in segments:
        txt = clean_whisper_hallucinations(seg['text'])
        
        # Filtros de calidad básicos
        if len(txt) < 1: continue
        if re.match(r'^[.,;?!]+$', txt): continue # Solo puntuación
        
        # Evitar duplicados exactos consecutivos
        if full_text_parts and txt.strip() == full_text_parts[-1].strip():
            continue

        seg['text'] = txt
        clean_segments.append(seg)
        full_text_parts.append(txt)
        
    return clean_segments, " ".join(full_text_parts)

# --- 4. CORRECCIÓN LLM ---
def text_chunker_smart(text, chunk_size=3000):
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
    chunks = text_chunker_smart(text)
    final_parts = []
    
    progress_text = "🧠 Corrigiendo tildes (Llama 3)..."
    my_bar = st.progress(0, text=progress_text)
    
    system_prompt = """Eres un corrector ortográfico experto.
TAREA: Agrega tildes y corrige puntuación básica al texto en español proporcionado.
REGLAS:
1. NO cambies el vocabulario (mantén regionalismos).
2. NO resumas.
3. Devuelve EL MISMO TEXTO pero con las tildes correctas.
4. Si el texto no tiene sentido, devuélvelo tal cual."""

    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant", # Modelo más rápido y obediente para esto
                temperature=0.1,
                max_tokens=len(chunk) + 200
            )
            corrected = response.choices[0].message.content.strip()
            
            # Validación de longitud (para evitar que el LLM se coma texto)
            diff = abs(len(corrected) - len(chunk))
            if diff > len(chunk) * 0.2: # Si cambia más del 20%, rechazar
                final_parts.append(chunk)
            else:
                final_parts.append(corrected)
        except:
            final_parts.append(chunk)
        my_bar.progress((i + 1) / len(chunks))
    
    my_bar.empty()
    return " ".join(final_parts)

# --- UTILIDADES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #ddd; background: #fff; cursor: pointer;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
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

def answer_question(q, text, client, history):
    msgs = [{"role": "system", "content": "Eres un asistente útil que responde basándose EXCLUSIVAMENTE en el texto proporcionado."}]
    for item in history:
        msgs.append({"role": "user", "content": item['question']})
        msgs.append({"role": "assistant", "content": item['answer']})
    msgs.append({"role": "user", "content": f"Contexto:\n{text[:25000]}\n\nPregunta: {q}"})
    try:
        return client.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- UI PRINCIPAL ---
with st.sidebar:
    st.header("⚙️ Opciones")
    mode = st.radio("Modo:", ["Whisper Puro (Rápido)", "Corrección Tildes (Lento)"], index=1)
    st.info("✅ Audio Fix aplicado: Rango dinámico completo (sin cortes de frecuencia).")

uploaded_file = st.file_uploader("Arrastra tu archivo aquí", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov", "flac", "aac"])

if st.button("🚀 Transcribir Ahora", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    client = Groq(api_key=api_key)
    
    try:
        # 1. AUDIO PROCESSING
        with st.spinner("🎧 Optimizando audio (Normalización segura)..."):
            audio_bytes, optimized = optimize_audio_safe(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = audio_bytes

        # 2. WHISPER TRANSCRIPTION
        with st.spinner("📝 Transcribiendo..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            # Prompt NEUTRO para evitar leakage
            safe_prompt = "Esta es una transcripción de una conversación en español clara y natural."
            
            with open(tmp_path, "rb") as f:
                transcription_data = client.audio.transcriptions.create(
                    file=("audio.mp3", f.read()),
                    model="whisper-large-v3",
                    language="es",
                    response_format="verbose_json",
                    temperature=0.0,
                    prompt=safe_prompt
                )
            os.unlink(tmp_path)

        # 3. CLEANING
        segments_cleaned, text_cleaned = filter_segments_data(transcription_data.segments)
        
        # 4. CORRECTION
        if mode == "Corrección Tildes (Lento)":
            final_text = surgical_correction(text_cleaned, client)
        else:
            final_text = text_cleaned
            
        st.session_state.transcription_text = final_text
        st.session_state.segments = segments_cleaned
        st.balloons()
        st.rerun()
        
    except Exception as e:
        st.error(f"Ocurrió un error: {e}")

# --- DISPLAY ---
if 'transcription_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📄 Transcripción", "💬 Chat"])
    
    with tab1:
        col1, col2 = st.columns([3, 1])
        query = col1.text_input("Buscar palabra:", key="search_input")
        col2.write(""); col2.button("Borrar", on_click=clear_search_callback)
        
        if query:
            count = 0
            with st.expander(f"Resultados para '{query}'", expanded=True):
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        count += 1
                        c1, c2 = st.columns([0.2, 0.8])
                        c1.button(f"⏱ {format_timestamp(seg['start'])}", key=f"s_{i}", on_click=set_audio_time, args=(seg['start'],))
                        c2.markdown(seg['text'].replace(query, f"**{query}**"))
                if count == 0: st.caption("No encontrado.")
        
        st.text_area("Texto Completo:", st.session_state.transcription_text, height=500)
        c1, c2, c3 = st.columns(3)
        c1.download_button("Descargar TXT", st.session_state.transcription_text, "transcripcion.txt")
        c2.download_button("Descargar SRT", export_to_srt(st.session_state.segments), "subtitulos.srt")
        with c3: create_copy_button(st.session_state.transcription_text)

    with tab2:
        for msg in st.session_state.qa_history:
            st.chat_message("user").write(msg['question'])
            st.chat_message("assistant").write(msg['answer'])
        if p := st.chat_input("Pregunta sobre el texto..."):
            st.session_state.qa_history.append({"question": p, "answer": "..."})
            ans = answer_question(p, st.session_state.transcription_text, Groq(api_key=api_key), st.session_state.qa_history[:-1])
            st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()
