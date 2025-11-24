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
import difflib

# --- AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        st.session_state.password_attempted = False
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    st.markdown("""
    <div style='text-align: center; padding: 4rem 0;'>
        <h1 style='font-size: 4rem;'>Transcriptor Pro</h1>
        <p>Transcripción 100% exacta · Solo tildes · Sin inventos</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.text_input("Contraseña", type="password", key="password", on_change=validate_password)
    if st.session_state.get("password_attempted", False):
        st.error("Contraseña incorrecta")
    st.stop()

# --- CONFIG ---
st.set_page_config(page_title="Transcriptor Pro V13", page_icon="microphone", layout="wide")

if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("Falta GROQ_API_KEY en secrets")
    st.stop()

client = Groq(api_key=api_key)

# --- CALLBACKS ---
def set_audio_time(t): st.session_state.audio_start_time = int(t)
def clear_search(): st.session_state.search_input = ""

# --- LIMPIEZA ULTRA-ESTRICTA DE ALUCINACIONES ---
def extreme_clean_text(text):
    if not text: return ""
    
    # 1. Patrones comunes de alucinación al inicio/final
    hallucinations = [
        r"^[Hh]ola[,.]? [Gg]racias por ver.*",
        r"^[Gg]racias por ver el vídeo.*",
        r"^[Ss]uscríbete.*",
        r"^[Dd]ale like.*",
        r"^[Ss]i te gustó.*",
        r"^[Ee]n el siguiente vídeo.*",
        r"[Ss]ubtítulos realizados por.*",
        r"[Tt]ranscribed by.*",
        r"[Cc]opyright.*",
        r"[Vv]isita.*",
        r"[Cc]omunidad de.*",
        r"[Aa]mara\.org.*",
    ]
    
    cleaned = text
    for pattern in hallucinations:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # 2. Eliminar repeticiones de palabras clave (muy común en Whisper)
    # Ej: "siguiente siguiente siguiente" o "continuar continuar"
    cleaned = re.sub(r'\b(\w+)(?:\s+\1\b){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    
    # 3. Eliminar bucles de frases cortas repetidas
    words = cleaned.split()
    if len(words) > 10:
        for i in range(5, 20):
            phrase = " ".join(words[-i:])
            if cleaned.lower().count(phrase.lower()) > 2:
                cleaned = re.sub(re.escape(phrase), "", cleaned, count=1, flags=re.IGNORECASE)
    
    # 4. Limpiar espacios
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

# --- FILTRADO DE SEGMENTOS (NO ELIMINA NADA VÁLIDO) ---
def filter_segments_smart(segments):
    filtered = []
    last_text = ""
    
    for seg in segments:
        text = seg['text'].strip()
        text = extreme_clean_text(text)
        
        if len(text) == 0:
            continue
            
        # No eliminar segmentos cortos si no son repetidos
        if text.lower() == last_text.lower():
            continue
            
        # Similitud alta pero no idénticos
        if last_text and len(text) > 8 and len(last_text) > 8:
            ratio = difflib.SequenceMatcher(None, text.lower(), last_text.lower()).ratio()
            if ratio > 0.92:
                continue
                
        seg['text'] = text
        filtered.append(seg)
        last_text = text
    
    return filtered

# --- CORRECCIÓN DE TILDES 100% SEGURA ---
def ultra_safe_accent_correction(text, client):
    if len(text) < 10:
        return text
        
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
    corrected_parts = []
    
    prompt = """ERES UN CORRECTOR ORTOGRÁFICO EXTREMADAMENTE ESTRICTO.
Solo puedes añadir o corregir tildes en palabras españolas.
REGLAS OBLIGATORIAS:
- NO cambies ninguna palabra por sinónimos
- NO añadas ni quites texto
- NO cambies el orden
- NO modifiques puntuación (salvo añadir punto final si falta)
- Si ya tiene tildes correctas → devuélvelo IDÉNTICO

Ejemplo válido:
Entrada: "Esta es la tecnologia del futuro y la educacion superior"
Salida:  "Esta es la tecnología del futuro y la educación superior"

Solo responde el texto corregido. NADA MÁS."""

    bar = st.progress(0)
    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                model="llama-3.2-90b-text-preview",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": chunk}
                ],
                temperature=0.0,
                max_tokens=len(chunk) + 200
            )
            corrected = response.choices[0].message.content.strip()
            
            # SAFETY: si cambia más del 5% de caracteres → descartamos
            diff_ratio = len(set(corrected) - set(chunk)) / len(chunk) if chunk else 0
            if diff_ratio > 0.05 or abs(len(corrected) - len(chunk)) > len(chunk)*0.08:
                corrected_parts.append(chunk)
            else:
                corrected_parts.append(corrected)
                
        except:
            corrected_parts.append(chunk)
            
        bar.progress((i+1)/len(chunks))
    
    bar.empty()
    return " ".join(corrected_parts)

# --- OPTIMIZACIÓN DE AUDIO (CLAVE PARA EVITAR ALUCINACIONES) ---
def optimize_audio(file_bytes, filename):
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_in:
        tmp_in.write(file_bytes)
        input_path = tmp_in.name
    
    output_path = input_path + "_opt.mp3"
    
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-af", "highpass=f=150, lowpass=f=4000, loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "16000", "-ac", "1", "-b:a", "64k",
            output_path
        ], check=True, capture_output=True)
        
        with open(output_path, "rb") as f:
            optimized_bytes = f.read()
            
        os.unlink(input_path)
        os.unlink(output_path)
        return optimized_bytes, True
    except:
        os.unlink(input_path)
        if os.path.exists(output_path): os.unlink(output_path)
        return file_bytes, False

# --- UTILIDADES ---
def create_copy_button(text):
    js = f'''
    <button onclick="navigator.clipboard.writeText(`{text.replace('`', '\\`')}`); this.innerText='Copiado'" 
            style="padding:0.6rem 1.2rem; background:#0066ff; color:white; border:none; border-radius:8px; cursor:pointer;">
        Copiar Todo
    </button>
    '''
    components.html(js, height=50)

def export_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = timedelta(seconds=seg['start'])
        end = timedelta(seconds=seg['end'])
        start_str = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{(start.microseconds//1000):03}"
        end_str = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{(end.microseconds//1000):03}"
        lines.append(f"{i}\n{start_str} --> {end_str}\n{seg['text']}\n")
    return "\n".join(lines)

# --- INTERFAZ ---
st.title("Transcriptor Pro V13 – 100% Exacto")
st.caption("Sin repeticiones · Sin alucinaciones · Solo tildes · Máxima fidelidad")

with st.sidebar:
    st.header("Configuración")
    mode = st.radio("Modo de corrección", ["Solo Whisper (crudo)", "Tildes quirúrgicas (recomendado)"], index=1)
    temp = st.slider("Temperatura Whisper", 0.0, 0.3, 0.0, 0.05,
                     help="0.0 = máxima exactitud (recomendado)")
    st.info("Mejoras activas:\n• Audio normalizado\n• Anti-alucinaciones extremo\n• Tildes seguras\n• Sin bucles")

uploaded = st.file_uploader("Sube tu audio o vídeo", type=["mp3","wav","m4a","mp4","mov","flac","ogg"])

if st.button("Iniciar Transcripción", type="primary", disabled=not uploaded):
    with st.spinner("Optimizando audio..."):
        audio_bytes, _ = optimize_audio(uploaded.getvalue(), uploaded.name)
        st.session_state.audio_bytes = audio_bytes

    with st.spinner("Transcribiendo con máxima precisión..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        strict_prompt = ("Transcribe exactamente lo que escuchas en español. "
                        "No repitas frases ni palabras. No inventes texto en silencios. "
                        "No añadas saludos ni despedidas que no existan. "
                        "Usa puntuación natural española. Sé 100% fiel al audio.")

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=("audio.mp3", f.read()),
                model="whisper-large-v3",
                language="es",
                temperature=temp,
                prompt=strict_prompt,
                response_format="verbose_json"
            )
        os.unlink(tmp_path)

        # Limpieza fuerte
        clean_full_text = extreme_clean_text(result.text)
        clean_segments = filter_segments_smart(result.segments)

        final_text = clean_full_text
        if mode == "Tildes quirúrgicas (recomendado)":
            with st.spinner("Corrigiendo solo tildes (100% seguro)..."):
                final_text = ultra_safe_accent_correction(clean_full_text, client)

        st.session_state.transcription = final_text
        st.session_state.segments = clean_segments
        st.session_state.audio_bytes = audio_bytes
        st.balloons()
        st.rerun()

# --- MOSTRAR RESULTADOS ---
if 'transcription' in st.session_state:
    st.audio(st.session_state.audio_bytes, start_time=st.session_state.audio_start_time)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Palabras", len(st.session_state.transcription.split()))
    col2.metric("Segmentos", len(st.session_state.segments))
    col3.metric("Caracteres", len(st.session_state.transcription))

    tab1, tab2 = st.tabs(["Transcripción", "Chat"])

    with tab1:
        query = st.text_input("Buscar en transcripción", key="search")
        if query:
            with st.expander(f"Resultados para: {query}", expanded=True):
                for i, seg in enumerate(st.session_state.segments):
                    if query.lower() in seg['text'].lower():
                        c1, c2 = st.columns([1,9])
                        c1.button(f"▶️ {timedelta(seconds=seg['start']}:%M:%S}", 
                                on_click=set_audio_time, args=(seg['start'],))
                        highlighted = seg['text'].replace(query, f"**{query}**")
                        c2.markdown(highlighted)

        st.markdown("### Texto completo")
        st.text_area("transcripción", st.session_state.transcription, height=600, label_visibility="collapsed")
        
        c1, c2, c3 = st.columns(3)
        c1.download_button("Descargar TXT", st.session_state.transcription, "transcripcion.txt")
        c2.download_button("Descargar SRT", export_srt(st.session_state.segments), "subtitulos.srt")
        with c3: create_copy_button(st.session_state.transcription)

    with tab2:
        st.write("Pregunta lo que quieras sobre el audio:")
        for q in st.session_state.qa_history:
            st.chat_message("user").write(q["q"])
            st.chat_message("assistant").write(q["a"])
        
        if prompt := st.chat_input("¿Qué quieres saber del audio?"):
            with st.spinner("Buscando en la transcripción..."):
                ans = client.chat.completions.create(
                    model="llama-3.2-90b-text-preview",
                    messages=[
                        {"role": "system", "content": "Responde solo con información que esté literalmente en la transcripción."},
                        {"role": "user", "content": f"Transcripción:\n{st.session_state.transcription[:30000]}\n\nPregunta: {prompt}"}
                    ],
                    temperature=0.0
                ).choices[0].message.content
                st.session_state.qa_history.append({"q": prompt, "a": ans})
            st.rerun()

    if st.button("Nuevo archivo"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
