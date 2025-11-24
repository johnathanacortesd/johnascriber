import streamlit as st
from openai import OpenAI
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
import glob
import shutil

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
        <h2>Transcriptor Pro - Precisión Studio</h2>
        <p style='color: #666; margin-bottom: 2rem;'>Motor OpenAI (No salta audio) + Corrección Groq</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    
    if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
        st.error("❌ Contraseña incorrecta.")
    st.stop()

# --- CONFIGURACIÓN APP ---
st.set_page_config(page_title="Transcriptor Preciso V14", page_icon="🎙️", layout="wide")

# --- ESTADO ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

# --- VERIFICACIÓN DE CLAVES ---
try:
    groq_api_key = st.secrets["GROQ_API_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"] # NUEVO REQUISITO
except KeyError:
    st.error("❌ Error: Faltan claves en secrets. Necesitas GROQ_API_KEY y OPENAI_API_KEY.")
    st.info("💡 Usa OpenAI para transcribir (sin errores) y Groq para corregir/chat (gratis).")
    st.stop()

# --- CALLBACKS ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

def clear_search_callback():
    st.session_state.search_input = ""

# --- FUNCIONES DE LIMPIEZA ---
def clean_hallucinations(text):
    if not text: return ""
    junk = [r"Subtítulos por.*", r"Amara\.org.*", r"Transcribed by.*", r"Copyright.*"]
    cleaned = text
    for p in junk:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

# --- CORRECCIÓN QUIRÚRGICA (Con Groq para velocidad) ---
def text_chunker_smart(text, chunk_size=2500):
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

def surgical_correction(text, client_groq):
    """Usa Groq (Llama3) solo para poner tildes. Es rápido y barato."""
    chunks = text_chunker_smart(text)
    final_parts = []
    my_bar = st.progress(0, text="🧠 Corrector Gramatical (Groq Llama 3)...")
    
    system_prompt = "Eres un corrector ortográfico. TU TAREA: Poner tildes. PROHIBIDO cambiar palabras. Si está bien, devuélvelo IDÉNTICO."

    for i, chunk in enumerate(chunks):
        try:
            response = client_groq.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk}],
                model="llama-3.1-8b-instant", temperature=0.0
            )
            corrected = response.choices[0].message.content.strip()
            # Safety Check
            if abs(len(corrected) - len(chunk)) / len(chunk) > 0.10: 
                final_parts.append(chunk)
            else:
                final_parts.append(corrected)
        except:
            final_parts.append(chunk)
        my_bar.progress((i + 1) / len(chunks))
    my_bar.empty()
    return " ".join(final_parts)

# --- SPLITTER PARA OPENAI ---
def split_audio_openai_safe(file_bytes, filename):
    """
    OpenAI tiene un límite de 25MB por archivo.
    Dividimos en trozos de 10 minutos (aprox 5-7MB en mp3) para estar seguros.
    No necesitamos cortes de 3 min porque OpenAI NO pierde contexto como Groq.
    """
    file_ext = os.path.splitext(filename)[1] or ".mp3"
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, f"original{file_ext}")
    
    with open(input_path, "wb") as f:
        f.write(file_bytes)

    # 1. Convertir a MP3 eficiente (64k es suficiente para voz perfecta)
    optimized_path = os.path.join(temp_dir, "optimized.mp3")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path, 
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", 
            "-f", "mp3", optimized_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        shutil.copy(input_path, optimized_path)

    # 2. Segmentar en 10 minutos (600s) - Seguro para API OpenAI
    chunk_pattern = os.path.join(temp_dir, "part%03d.mp3")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", optimized_path,
            "-f", "segment", "-segment_time", "600", 
            "-c", "copy", "-reset_timestamps", "1",
            chunk_pattern
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return [optimized_path], None, temp_dir

    chunks = sorted(glob.glob(os.path.join(temp_dir, "part*.mp3")))
    
    with open(optimized_path, 'rb') as f:
        full_audio_bytes = f.read()
            
    return chunks, full_audio_bytes, temp_dir

# --- UTILIDADES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""<button id="{button_id}" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; background: #fff;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick = function() {{const ta = document.createElement("textarea");ta.value = {text_json};document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn = document.getElementById("{button_id}");btn.innerText = "✅ Copiado";setTimeout(()=>{{btn.innerText="📋 Copiar Todo"}}, 2000);}};</script>"""
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

def answer_question(q, text, client_groq, history):
    msgs = [{"role": "system", "content": "Responde solo basándote en la transcripción."}]
    for item in history:
        msgs.append({"role": "user", "content": item['question']})
        msgs.append({"role": "assistant", "content": item['answer']})
    msgs.append({"role": "user", "content": f"Contexto: {text[:25000]}\nPregunta: {q}"})
    try:
        return client_groq.chat.completions.create(messages=msgs, model="llama-3.1-8b-instant").choices[0].message.content
    except Exception as e: return f"Error: {e}"

# --- MAIN UI ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    st.markdown("**Motor Transcripción:** OpenAI (Whisper-1)")
    st.markdown("**Motor Corrección/Chat:** Groq (Llama-3)")
    st.info("✅ Esta combinación garantiza que NO falten pedazos de audio.")
    
    correction_mode = st.radio("Corrección:", ["Ninguna", "Quirúrgica (Tildes)"], index=1)

uploaded_file = st.file_uploader("Sube audio/video", type=["mp3", "mp4", "wav", "m4a", "ogg", "mov"])

if st.button("🚀 Iniciar Transcripción (Alta Precisión)", type="primary", disabled=not uploaded_file):
    st.session_state.qa_history = []
    
    # Clientes
    client_openai = OpenAI(api_key=openai_api_key)
    client_groq = Groq(api_key=groq_api_key)
    
    try:
        # 1. PREPARACIÓN AUDIO
        with st.spinner("🔄 Preparando audio (FFmpeg)..."):
            chunks, full_audio, temp_dir = split_audio_openai_safe(uploaded_file.getvalue(), uploaded_file.name)
            st.session_state.uploaded_audio_bytes = full_audio
        
        all_segments = []
        full_text_accumulated = ""
        total_chunks = len(chunks)
        
        # 2. TRANSCRIPCIÓN CON OPENAI (ROBUSTA)
        progress_bar = st.progress(0, text="📝 Transcribiendo con OpenAI Whisper-1...")
        
        for i, chunk_path in enumerate(chunks):
            time_offset = i * 600 # 10 mins por chunk
            
            try:
                with open(chunk_path, "rb") as f:
                    # Usamos el modelo oficial de OpenAI
                    transcript = client_openai.audio.transcriptions.create(
                        file=f,
                        model="whisper-1",
                        language="es",
                        response_format="verbose_json",
                        temperature=0.0 # Determinístico
                    )
                
                # Procesar resultados
                clean_txt = clean_hallucinations(transcript.text)
                full_text_accumulated += clean_txt + " "
                
                # Ajustar timestamps
                for seg in transcript.segments:
                    seg['start'] += time_offset
                    seg['end'] += time_offset
                    seg['text'] = clean_hallucinations(seg['text'])
                    if len(seg['text']) > 1:
                        all_segments.append(seg)
                        
            except Exception as e:
                st.error(f"Error en parte {i+1}: {e}")
            
            progress_bar.progress((i + 1) / total_chunks)
            
        progress_bar.empty()
        shutil.rmtree(temp_dir, ignore_errors=True)

        # 3. CORRECCIÓN (USANDO GROQ PARA AHORRAR)
        if correction_mode == "Quirúrgico (Tildes)":
            final_text = surgical_correction(full_text_accumulated, client_groq)
        else:
            final_text = full_text_accumulated
            
        st.session_state.transcription_text = final_text
        st.session_state.segments = all_segments
        
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error: {e}")

# --- VISUALIZACIÓN ---
if 'transcription_text' in st.session_state:
    st.markdown("---")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)
    
    tab1, tab2 = st.tabs(["📝 Texto & Búsqueda", "💬 Chat"])
    
    with tab1:
        c1, c2 = st.columns([4, 1])
        q = c1.text_input("🔎 Buscar:", key="search_input")
        c2.write(""); c2.button("✖️", on_click=clear_search_callback)
        
        if q:
            found = False
            with st.expander(f"Resultados: {q}", expanded=True):
                for i, seg in enumerate(st.session_state.segments):
                    if q.lower() in seg['text'].lower():
                        found = True
                        ctx = get_extended_context(st.session_state.segments, i)
                        for c in ctx:
                            bt_k = f"t_{i}_{c['start']}"
                            col_a, col_b = st.columns([0.15, 0.85])
                            col_a.button(f"▶ {c['time']}", key=bt_k, on_click=set_audio_time, args=(c['start'],))
                            
                            txt = c['text']
                            if c['is_match']: txt = re.sub(re.escape(q), f"**{q.upper()}**", txt, flags=re.IGNORECASE)
                            col_b.markdown(txt)
                        st.divider()
                if not found: st.warning("Sin resultados.")

        st.text_area("Texto Completo:", st.session_state.transcription_text, height=600, label_visibility="collapsed")
        
        ca, cb, cc = st.columns(3)
        ca.download_button("💾 TXT", st.session_state.transcription_text, "trans.txt", use_container_width=True)
        cb.download_button("💾 SRT", export_to_srt(st.session_state.segments), "subs.srt", use_container_width=True)
        with cc: create_copy_button(st.session_state.transcription_text)

    with tab2:
        for m in st.session_state.qa_history:
            with st.chat_message("user"): st.write(m['question'])
            with st.chat_message("assistant"): st.write(m['answer'])
            
        if p := st.chat_input("Pregunta al audio..."):
            st.session_state.qa_history.append({"question": p, "answer": "..."})
            with st.spinner("Pensando..."):
                # Chat usa Groq (Gratis y rápido)
                ans = answer_question(p, st.session_state.transcription_text, Groq(api_key=groq_api_key), st.session_state.qa_history[:-1])
                st.session_state.qa_history[-1]["answer"] = ans
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Nuevo Archivo"): st.session_state.clear(); st.rerun()
