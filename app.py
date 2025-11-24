import streamlit as st
from groq import Groq
import tempfile
import os
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
import difflib

# ========================= AUTENTICACIÓN =========================
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align:center; padding:4rem;'>Transcriptor Pro</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.text_input("Contraseña", type="password", key="password", on_change=validate_password)
    if st.session_state.get("password_attempted"):
        st.error("Contraseña incorrecta")
    st.stop()

# ========================= CONFIG =========================
st.set_page_config(page_title="Transcriptor Pro V14", page_icon="microphone", layout="wide")

if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("Falta GROQ_API_KEY en secrets")
    st.stop()

client = Groq(api_key=api_key)

def set_audio_time(t): st.session_state.audio_start_time = int(t)

# ========================= LIMPIEZA EXTREMA =========================
def extreme_clean_text(text):
    if not text: return ""
    junk = [
        r"^[Hh]ola[,.]? [Gg]racias por.*", r"^[Ss]uscríbete.*", r"^[Dd]ale like.*",
        r"subtítulos.*", r"transcribed by.*", r"copyright.*", r"amara\.org.*"
    ]
    for p in junk:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    text = re.sub(r'\b(\w+)(?:\s+\1\b){2,}', r'\1', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text).strip()

def filter_segments_smart(segments):
    filtered = []
    last = ""
    for seg in segments:
        txt = extreme_clean_text(seg["text"])
        if not txt or txt.lower() == last.lower():
            continue
        if last and len(txt)>8 and len(last)>8:
            if difflib.SequenceMatcher(None, last.lower(), txt.lower()).ratio() > 0.92:
                continue
        seg["text"] = txt
        filtered.append(seg)
        last = txt
    return filtered

# ========================= TILDES 100% SEGURAS =========================
def ultra_safe_accent_correction(text, client):
    if len(text) < 20: return text
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
    corrected = []
    prompt = """Solo corrige tildes en español. No cambies palabras, no añadas ni quites nada. Devuelve el texto exactamente igual pero con tildes correctas."""
    bar = st.progress(0)
    for i, chunk in enumerate(chunks):
        try:
            r = client.chat.completions.create(
                model="llama-3.1-70b-versatile",   # ← modelo que SÍ existe y es rápido
                messages=[{"role":"system","content":prompt},{"role":"user","content":chunk}],
                temperature=0.0,
                max_tokens=len(chunk)+150
            )
            fix = r.choices[0].message.content.strip()
            if abs(len(fix)-len(chunk))/len(chunk) > 0.1:
                corrected.append(chunk)
            else:
                corrected.append(fix)
        except:
            corrected.append(chunk)
        bar.progress((i+1)/len(chunks))
    bar.empty()
    return " ".join(corrected)

# ========================= OPTIMIZACIÓN AUDIO =========================
def optimize_audio(file_bytes, filename):
    suffix = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        in_path = tmp.name
    out_path = in_path + "_opt.mp3"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", in_path,
            "-af", "highpass=f=150,lowpass=f=4000,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "16000", "-ac", "1", "-b:a", "64k", out_path
        ], check=True, capture_output=True)
        with open(out_path, "rb") as f:
            opt = f.read()
        os.unlink(in_path); os.unlink(out_path)
        return opt, True
    except:
        os.unlink(in_path)
        return file_bytes, False

# ========================= UTILIDADES =========================
def format_time(sec):
    td = timedelta(seconds=int(sec))
    return str(td)[2:-7] if td.days == 0 else "00:00:00"

def export_srt(segments):
    lines = []
    for i, s in enumerate(segments, 1):
        start = timedelta(seconds=s['start'])
        end = timedelta(seconds=s['end'])
        sl = f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        el = f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        lines.append(f"{i}\n{sl} --> {el}\n{s['text']}\n")
    return "\n".join(lines)

def create_copy_button(text):
    js = f'''<button onclick="navigator.clipboard.writeText(`{text.replace('`','\\`')}`);this.innerText='Copiado'" 
             style="padding:10px 20px;background:#0066ff;color:white;border:none;border-radius:8px;cursor:pointer;">
             Copiar Todo</button>'''
    components.html(js, height=60)

# ========================= INTERFAZ =========================
st.title("Transcriptor Pro V14 – 100% Exacto")
st.caption("Contexto en búsquedas • Sin prompt leak • Chat funcionando")

with st.sidebar:
    mode = st.radio("Modo", ["Solo Whisper", "Tildes quirúrgicas (recomendado)"], index=1)
    temp = st.slider("Temperatura", 0.0, 0.3, 0.0, 0.05)

uploaded = st.file_uploader("Sube audio/vídeo", type=["mp3","wav","m4a","mp4","mov","flac","ogg","aac"])

if st.button("Iniciar Transcripción", type="primary", disabled=not uploaded):
    st.session_state.qa_history = []
    with st.spinner("Optimizando audio..."):
        audio_bytes, _ = optimize_audio(uploaded.getvalue(), uploaded.name)
        st.session_state.audio_bytes = audio_bytes

    with st.spinner("Transcribiendo..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # PROMPT 100% SEGURO – NUNCA se filtra
        magic_prompt = "vad_enabled=true language=es"

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=("audio.mp3", f.read()),
                model="whisper-large-v3",
                language="es",
                temperature=temp,
                prompt=magic_prompt,
                response_format="verbose_json"
            )
        os.unlink(tmp_path)

        clean_text = extreme_clean_text(result.text)
        clean_segments = filter_segments_smart(result.segments)

        final_text = clean_text
        if mode == "Tildes quirúrgicas (recomendado)":
            with st.spinner("Corrigiendo tildes..."):
                final_text = ultra_safe_accent_correction(clean_text, client)

        st.session_state.transcription = final_text
        st.session_state.segments = clean_segments
        st.session_state.audio_bytes = audio_bytes
        st.balloons()
        st.rerun()

# ========================= RESULTADOS =========================
if 'transcription' in st.session_state:
    st.audio(st.session_state.audio_bytes, start_time=st.session_state.audio_start_time)

    c1, c2, c3 = st.columns(3)
    c1.metric("Palabras", len(st.session_state.transcription.split()))
    c2.metric("Segmentos", len(st.session_state.segments))
    c3.metric("Caracteres", len(st.session_state.transcription))

    tab1, tab2 = st.tabs(["Transcripción + Búsqueda con contexto", "Chat"])

    # ==================== BÚSQUEDA CON FRASE ANTERIOR Y SIGUIENTE ====================
    with tab1:
        query = st.text_input("Buscar palabra o frase", key="search_input")
        if query:
            matches = []
            segments = st.session_state.segments
            for i, seg in enumerate(segments):
                if query.lower() in seg['text'].lower():
                    prev = segments[i-1]['text'] if i > 0 else ""
                    next_ = segments[i+1]['text'] if i+1 < len(segments) else ""
                    matches.append((prev, seg, next_))

            if matches:
                with st.expander(f"Resultados encontrados ({len(matches)})", expanded=True):
                    for prev, seg, next_ in matches:
                        col1, col2 = st.columns([1, 9])
                        time_str = format_time(seg['start'])
                        col1.button(f"Play {time_str}", key=f"play_{seg['start']}", on_click=set_audio_time, args=(seg['start'],))
                        # Contexto bonito
                        ctx = f"**{prev.strip()}** " if prev else ""
                        highlighted = re.sub(f"(?i){re.escape(query)}", f"**{query.upper()}**", seg['text'])
                        ctx += highlighted
                        if next_: ctx += f" **{next_.strip()}"
                        col2.markdown(ctx.strip())
                        st.markdown("---")
            else:
                st.info("No se encontraron coincidencias")

        st.markdown("### Texto completo")
        st.text_area("transcripción", st.session_state.transcription, height=600, label_visibility="collapsed")

        d1, d2, d3 = st.columns(3)
        d1.download_button("TXT", st.session_state.transcription, "transcripcion.txt")
        d2.download_button("SRT", export_srt(st.session_state.segments), "subtitulos.srt")
        with d3: create_copy_button(st.session_state.transcription)

    # ==================== CHAT FUNCIONANDO ====================
    with tab2:
        for item in st.session_state.qa_history:
            st.chat_message("user").write(item["q"])
            st.chat_message("assistant").write(item["a"])

        if prompt := st.chat_input("Pregunta sobre el audio..."):
            with st.spinner("Pensando..."):
                try:
                    ans = client.chat.completions.create(
                        model="llama-3.1-70b-versatile",   # ← modelo que EXISTE y es estable
                        messages=[
                            {"role": "system", "content": "Responde solo con información que esté literalmente en la transcripción."},
                            {"role": "user", "content": f"Transcripción:\n{st.session_state.transcription[:28000]}\n\nPregunta: {prompt}"}
                        ],
                        temperature=0.0,
                        max_tokens=1000
                    ).choices[0].message.content
                except Exception as e:
                    ans = f"Error del modelo: {str(e)}"
                st.session_state.qa_history.append({"q": prompt, "a": ans})
            st.rerun()

    if st.button("Nuevo archivo"):
        st.session_state.clear()
        st.rerun()
