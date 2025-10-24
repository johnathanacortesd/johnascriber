import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta

# Importar para conversión de audio
try:
    from moviepy.editor import VideoFileClip, AudioFileClip
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
        if "password" in st.session_state: del st.session_state["password"]
    else:
        st.session_state.password_correct = False
        st.session_state.password_attempted = True

if not st.session_state.password_correct:
    st.markdown("<div style='text-align: center; padding: 2rem 0;'><h1 style='color: #1f77b4; font-size: 3rem;'>🎙️</h1><h2>Transcriptor Pro - Johnascriptor</h2><p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA</p></div>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
        if st.session_state.get("password_attempted", False):
            st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    st.stop()

# --- INICIO DE LA APP ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- INICIALIZACIÓN DE ESTADO SEGURA ---
for key, default_value in {'audio_start_time': 0, 'search_counter': 0, 'last_search': "", 'qa_history': [], 'transcription_id': 0}.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit.", icon="🚨")
    st.stop()

# --- FUNCIONES AUXILIARES Y DE PROCESAMIENTO ---
def get_file_size_mb(file_bytes): return len(file_bytes) / (1024 * 1024)
def format_timestamp(seconds): return str(timedelta(seconds=int(seconds)))
def export_to_srt(data):
    srt=[]
    for i,seg in enumerate(data.segments,1):
        start=timedelta(seconds=seg['start']);end=timedelta(seconds=seg['end'])
        start_str=f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str=f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt.append(f"{i}\n{start_str} --> {end_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt)

# --- FUNCIONES DE CONVERSIÓN DE ARCHIVOS ---
def convert_video_to_audio(video_bytes, filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False,suffix=os.path.splitext(filename)[1]) as tmp_video:
            tmp_video.write(video_bytes); video_path=tmp_video.name
        audio_path=f"{video_path}_audio.mp3"
        video=VideoFileClip(video_path); video.audio.write_audiofile(audio_path,codec='mp3',bitrate='128k',verbose=False,logger=None); video.close()
        with open(audio_path,'rb') as f: audio_bytes=f.read()
        os.unlink(video_path); os.unlink(audio_path)
        return audio_bytes, True
    except Exception: return video_bytes, False

def compress_audio(audio_bytes, filename):
    try:
        with tempfile.NamedTemporaryFile(delete=False,suffix=os.path.splitext(filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes); audio_path=tmp_audio.name
        compressed_path=f"{audio_path}_compressed.mp3"
        audio=AudioFileClip(audio_path); audio.write_audiofile(compressed_path,codec='mp3',bitrate='96k',verbose=False,logger=None); audio.close()
        with open(compressed_path,'rb') as f: compressed_bytes=f.read()
        os.unlink(audio_path); os.unlink(compressed_path)
        return compressed_bytes
    except Exception: return audio_bytes

# --- NUEVA FUNCIÓN DE CORRECCIÓN CON IA ---
def correct_transcription_with_llm(raw_text, client):
    try:
        # PROMPT DE CORRECCIÓN MEJORADO
        prompt = """Eres un editor de transcripciones para un noticiero de Colombia. Tu única tarea es corregir el siguiente texto.
Reglas estrictas:
1.  Corrige errores ortográficos y gramaticales.
2.  Añade las tildes faltantes (ej: 'saco' -> 'sacó', 'pais' -> 'país').
3.  Completa palabras que parezcan cortadas o incompletas (ej: 'autocr' -> 'autocrítica', 'merec' -> 'merecían').
4.  Asegura que los signos de puntuación tengan sentido.
5.  NO añadas contenido nuevo, no resumas, no cambies el significado. Solo corrige.
6.  Devuelve únicamente el texto corregido, sin ninguna introducción o comentario.

Texto a corregir:
---
"""
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=4000
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"⚠️ No se pudo aplicar la corrección por IA. Mostrando transcripción original. Error: {e}")
        return raw_text

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(text, client):
    try:
        completion=client.chat.completions.create(messages=[{"role":"system","content":"Eres un analista de noticias experto. Crea un resumen ejecutivo conciso en un solo párrafo. Regla estricta: NO incluyas frases introductorias. Comienza directamente con el contenido."},{"role":"user","content":f"Genera un resumen ejecutivo en un párrafo (máx 150 palabras) de la transcripción. Empieza directamente, sin preámbulos.\n\nTranscripción:\n{text}"}],model="llama-3.1-8b-instant",temperature=0.3,max_tokens=500)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def answer_question(question, text, client, history):
    try:
        messages=[{"role":"system","content":"Eres un asistente experto. Responde preguntas sobre la transcripción de manera precisa, basándote ÚNICAMENTE en su contenido. Si la información no está, indícalo claramente."}]
        for qa in history: messages.extend([{"role":"user","content":qa["question"]},{"role":"assistant","content":qa["answer"]}])
        messages.append({"role":"user","content":f"Transcripción:\n---\n{text}\n---\nPregunta: {question}\nResponde basándote solo en la transcripción."})
        completion=client.chat.completions.create(messages=messages,model="llama-3.1-8b-instant",temperature=0.2,max_tokens=800)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")
with st.sidebar:
    st.header("⚙️ Configuración");model_option=st.selectbox("Modelo",["whisper-large-v3"]);language=st.selectbox("Idioma",["es"]);temperature=st.slider("Temperatura",0.0,1.0,0.0,0.1);st.markdown("---");st.subheader("🎯 Análisis Inteligente");enable_summary=st.checkbox("📝 Generar resumen",value=True);enable_entities=st.checkbox("👥 Extraer Entidades",value=True);st.markdown("---");st.subheader("🔧 Procesamiento");
    if MOVIEPY_AVAILABLE:st.info("💡 Videos > 25 MB se convertirán a audio.");compress_audio_option=st.checkbox("📦 Comprimir audio",value=False)
    else:st.warning("⚠️ MoviePy no disponible.");compress_audio_option=False
    st.markdown("---");st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
uploaded_file=st.file_uploader("Selecciona un archivo",type=["mp3","mp4","wav","webm","m4a","mpeg","mpga"],label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción",type="primary",use_container_width=True,disabled=not uploaded_file):
    keys_to_clear=['transcription','transcription_data','uploaded_audio_bytes','summary','people','brands']
    for key in keys_to_clear:
        if key in st.session_state: del st.session_state[key]
    st.session_state.update(audio_start_time=0,last_search="",qa_history=[],search_counter=st.session_state.search_counter+1)
    
    with st.spinner("🔄 Procesando archivo..."):
        try:
            file_bytes=uploaded_file.getvalue();original_size=get_file_size_mb(file_bytes)
            if os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4','.mpeg','.webm'] and MOVIEPY_AVAILABLE and original_size>25:
                with st.spinner(f"🎬 Video ({original_size:.2f} MB) a audio..."):
                    file_bytes,converted=convert_video_to_audio(file_bytes,uploaded_file.name)
                    if converted:st.success(f"✅ Convertido a {get_file_size_mb(file_bytes):.2f} MB")
            if MOVIEPY_AVAILABLE and compress_audio_option:
                with st.spinner("📦 Comprimiendo audio..."):
                    size_before=get_file_size_mb(file_bytes);file_bytes=compress_audio(file_bytes,uploaded_file.name);st.success(f"✅ Comprimido: {size_before:.2f} MB → {get_file_size_mb(file_bytes):.2f} MB")
            
            st.session_state.uploaded_audio_bytes=file_bytes;client=Groq(api_key=api_key)
            with tempfile.NamedTemporaryFile(delete=False,suffix='.mp3') as tmp:tmp.write(file_bytes);tmp_path=tmp.name
            
            with st.spinner("🔄 Transcribiendo con IA (Etapa 1/2)..."):
                with open(tmp_path,"rb") as audio_file:
                    prompt="Transcripción en español de Colombia."
                    transcription=client.audio.transcriptions.create(file=(uploaded_file.name,audio_file.read()),model=model_option,temperature=temperature,language=language,response_format="verbose_json",prompt=prompt)
            os.unlink(tmp_path)
            
            # --- PROCESO DE TRANSCRIPCIÓN DE DOS ETAPAS ---
            raw_text = transcription.text
            with st.spinner("🤖 Aplicando corrección y refinamiento con IA (Etapa 2/2)..."):
                corrected_text = correct_transcription_with_llm(raw_text, client)

            st.session_state.transcription = corrected_text
            # Guardamos la data original para timestamps, pero el texto a mostrar es el corregido
            st.session_state.transcription_data = transcription
            
            with st.spinner("🧠 Generando análisis sobre el texto corregido..."):
                if enable_summary:st.session_state.summary=generate_summary(corrected_text,client)
                # Las entidades se extraen del texto corregido para mayor precisión
                if enable_entities:
                    people,brands=extract_entities(corrected_text,client)
                    st.session_state.people,st.session_state.brands=enrich_entities_with_timestamps(people,brands,transcription.segments)
            
            st.success("✅ ¡Proceso completado!");st.balloons()
        except Exception as e:st.error(f"❌ Error en la transcripción: {e}",icon="🔥")

if 'transcription' in st.session_state:
    st.markdown("---");st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes,start_time=st.session_state.audio_start_time)

    tab_titles=["📝 Transcripción Corregida","📊 Resumen Interactivo"];
    if st.session_state.get('people') or st.session_state.get('brands'):tab_titles.append("👥 Entidades Clave")
    tabs=st.tabs(tab_titles)

    with tabs[0]:
        st.markdown("**📄 Transcripción completa y refinada por IA:**"); text_html=st.session_state.transcription.replace('\n','<br>')
        st.markdown(f"<div style='background-color:#0E1117;color:#FAFAFA;border:1px solid #333;border-radius:10px;padding:1.5rem;max-height:500px;overflow-y:auto;font-family:\"Source Code Pro\",monospace;white-space:pre-wrap;'>{text_html}</div>", unsafe_allow_html=True);st.write("")
        d1,d2,d3,d4=st.columns([2,2,2,1.5]);
        d1.download_button("💾 TXT Corregido",st.session_state.transcription.encode('utf-8'),"transcripcion_corregida.txt",use_container_width=True)
        d2.download_button("💾 TXT Original (Whisper)", st.session_state.transcription_data.text.encode('utf-8'), "transcripcion_original.txt", use_container_width=True)
        d3.download_button("💾 SRT Subtítulos",export_to_srt(st.session_state.transcription_data).encode('utf-8'),"subtitulos.srt",use_container_width=True)
        from streamlit.components.v1 import html
        def create_copy_button(text_to_copy):
            text_json = json.dumps(text_to_copy)
            button_id = f"copy-btn-{hash(text_to_copy)}"
            button_html = f"""<button id='{button_id}'>Copiar</button><script>document.getElementById('{button_id}').onclick=()=>{{navigator.clipboard.writeText({text_json}).then(()=>{{document.getElementById('{button_id}').innerText='Copiado!';setTimeout(()=>{{document.getElementById('{button_id}').innerText='Copiar'}},2000)}})}}</script>"""
            html(button_html)

    with tabs[1]:
        if 'summary' in st.session_state: st.markdown("### 📝 Resumen Ejecutivo"); st.markdown(st.session_state.summary); st.markdown("---")
        
        st.markdown("### 💭 Haz preguntas sobre el contenido")
        if st.session_state.qa_history:
            for i, qa in enumerate(st.session_state.qa_history):
                st.markdown(f"**P{i+1}:** {qa['question']}"); st.markdown(f"**R:** {qa['answer']}"); st.markdown("---")
        
        with st.form(key="q_form", clear_on_submit=True):
            user_question=st.text_area("Escribe tu pregunta:",placeholder="Ej: ¿Qué dijo [persona] sobre [tema]?",height=100)
            sq,ch=st.columns(2); submit_question=sq.form_submit_button("🚀 Enviar",use_container_width=True); clear_history=ch.form_submit_button("🗑️ Borrar Historial",use_container_width=True)

        if submit_question and user_question.strip():
            with st.spinner("🤔 Analizando..."):
                client=Groq(api_key=api_key); answer=answer_question(user_question,st.session_state.transcription,client,st.session_state.qa_history); st.session_state.qa_history.append({'question':user_question,'answer':answer}); st.rerun()
        if clear_history: st.session_state.qa_history=[]; st.rerun()

    if len(tabs) > 2:
        with tabs[2]:
            st.info("Las marcas de tiempo corresponden al audio original y pueden no alinearse perfectamente con el texto corregido por la IA.", icon="💡")
            if st.session_state.get('people'):
                # Código de entidades sin cambios
                st.markdown("### 👤 Personas y Cargos");
                for name, data in st.session_state.people.items():
                    st.markdown(f"**{name}** - *{data['details'].get('role', 'No especificado')}*")
                    if data['mentions']:
                        with st.expander(f"Ver {len(data['mentions'])} mención(es)"):
                            for m in data['mentions']:
                                c1,c2=st.columns([0.2,0.8]); c1.button(f"▶️ {m['time']}",key=f"p_{name}_{m['start']}",on_click=set_audio_time,args=(m['start'],)); c2.markdown(f"_{m['context']}_")
                st.markdown("---")
            if st.session_state.get('brands'):
                # Código de entidades sin cambios
                st.markdown("### 🏢 Marcas Mencionadas")
                for name, data in st.session_state.brands.items():
                    st.markdown(f"**{name}**")
                    if data['mentions']:
                        with st.expander(f"Ver {len(data['mentions'])} mención(es)"):
                            for m in data['mentions']:
                                c1,c2=st.columns([0.2,0.8]); c1.button(f"▶️ {m['time']}",key=f"b_{name}_{m['start']}",on_click=set_audio_time,args=(m['start'],)); c2.markdown(f"_{m['context']}_")
            if not st.session_state.get('people') and not st.session_state.get('brands'): st.info("No se identificaron entidades.")

    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
        pwd=st.session_state.password_correct; st.session_state.clear(); st.session_state.password_correct=pwd; st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'><p><strong>Transcriptor Pro - Johnascriptor - v3.9.0 (Whisper + Llama 3.1 Correction)</strong></p><p style='font-size: 0.85rem;'>✨ Con Corrección de Transcripción por IA</p></div>""", unsafe_allow_html=True)
