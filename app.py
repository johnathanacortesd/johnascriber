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
for key, default_value in {
    'audio_start_time': 0, 'search_counter': 0, 'last_search': "", 'qa_history': [], 'transcription_id': 0
}.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit.", icon="🚨")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES ORIGINAL Y COMPLETO ---
SPANISH_WORD_CORRECTIONS = {
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1', r'\badministraci(?!ón\b)\b': 'administración', r'\bAdministraci(?!ón\b)\b': 'Administración', r'\bcomunicaci(?!ón\b)\b': 'comunicación', r'\bComunicaci(?!ón\b)\b': 'Comunicación', r'\bdeclaraci(?!ón\b)\b': 'declaración', r'\bDeclaraci(?!ón\b)\b': 'Declaración', r'\bdonaci(?!ón\b)\b': 'donación', r'\bDonaci(?!ón\b)\b': 'Donación', r'\beducaci(?!ón\b)\b': 'educación', r'\bEducaci(?!ón\b)\b': 'Educación', r'\bfundaci(?!ón\b)\b': 'fundación', r'\bFundaci(?!ón\b)\b': 'Fundación', r'\bimplementaci(?!ón\b)\b': 'implementación', r'\bImplementaci(?!ón\b)\b': 'Implementación', r'\binformaci(?!ón\b)\b': 'información', r'\bInformaci(?!ón\b)\b': 'Información', r'\binscripci(?!ón\b)\b': 'inscripción', r'\bInscripci(?!ón\b)\b': 'Inscripción', r'\binvestigaci(?!ón\b)\b': 'investigación', r'\bInvestigaci(?!ón\b)\b': 'Investigación', r'\bnaci(?!ón\b)\b': 'nación', r'\bNaci(?!ón\b)\b': 'Nación', r'\bnavegaci(?!ón\b)\b': 'navegación', r'\bNavegaci(?!ón\b)\b': 'Navegación', r'\boperaci(?!ón\b)\b': 'operación', r'\bOperaci(?!ón\b)\b': 'Operación', r'\bopini(?!ón\b)\b': 'opinión', r'\bOpini(?!ón\b)\b': 'Opinión', r'\borganizaci(?!ón\b)\b': 'organización', r'\bOrganizaci(?!ón\b)\b': 'Organización', r'\bparticipaci(?!ón\b)\b': 'participación', r'\bParticipaci(?!ón\b)\b': 'Participación', r'\bpoblaci(?!ón\b)\b': 'población', r'\bPoblaci(?!ón\b)\b': 'Población', r'\bprotecci(?!ón\b)\b': 'protección', r'\bProtecci(?!ón\b)\b': 'Protección', r'\brelaci(?!ón\b)\b': 'relación', r'\bRelaci(?!ón\b)\b': 'Relación', r'\breuni(?!ón\b)\b': 'reunión', r'\bReuni(?!ón\b)\b': 'Reunión', r'\bresoluci(?!ón\b)\b': 'resolución', r'\bResoluci(?!ón\b)\b': 'Resolución', r'\bsanci(?!ón\b)\b': 'sanción', r'\bSanci(?!ón\b)\b': 'Sanción', r'\bsituaci(?!ón\b)\b': 'situación', r'\bSituaci(?!ón\b)\b': 'Situación', r'\bCancerolog(?!ía\b)\b': 'Cancerología', r'\bcompañí(?!a\b)\b': 'compañía', r'\beconomí(?!a\b)\b': 'economía', r'\benergí(?!a\b)\b': 'energía', r'\bgeografí(?!a\b)\b': 'geografía', r'\bmetodolog(?!ía\b)\b': 'metodología', r'\boncol(?!ógica\b)\b': 'oncológica', r'\bpolític(?!a\b)\b': 'política', r'\bRepúblic(?!a\b)\b': 'República', r'\btecnolog(?!ía\b)\b': 'tecnología', r'\bAméric(?!a\b)\b': 'América', r'\bBogot(?!á\b)\b': 'Bogotá', r'\bMéxic(?!o\b)\b': 'México', r'\bPer\b': 'Perú', r'\badem(?!ás\b)\b': 'además', r'\btambi(?!én\b)\b': 'también', r'\búltim(?!o\b)\b': 'último', r'\bdí\b': 'día', r'\bmiércole\b': 'miércoles', r'\bdocumenta\b': 'documental', r'\bsostenib\b': 'sostenible', r'\bentretenimient\b': 'entretenimiento', r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué', r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde', r'\b(E|e)l\s(es|fue|será)\b': r'\1l \2', r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json=json.dumps(text_to_copy);button_id=f"copy-button-{hash(text_to_copy)}"
    components.html(f"""<button id="{button_id}" style="width:100%;padding:0.25rem 0.5rem;border-radius:0.5rem;border:1px solid rgba(49,51,63,0.2);background-color:#FFF;color:#31333F;">📋 Copiar Todo</button><script>document.getElementById("{button_id}").onclick=function(){{const ta=document.createElement("textarea");ta.value={text_json};ta.style.position="fixed";ta.style.top="-9999px";document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);const btn=document.getElementById("{button_id}");const originalTxt=btn.innerText;btn.innerText="✅ ¡Copiado!";setTimeout(function(){{btn.innerText=originalTxt}},2000);}};</script>""",height=40)

def format_timestamp(seconds): return str(timedelta(seconds=int(seconds)))
def get_file_size_mb(file_bytes): return len(file_bytes) / (1024 * 1024)

def fix_spanish_encoding(text):
    if not text: return text
    result=text; encoding_fixes={'Ã¡':'á','Ã©':'é','Ã­':'í','Ã³':'ó','Ãº':'ú','Ã±':'ñ','Ã‘':'Ñ','Â¿':'¿','Â¡':'¡'}
    for wrong, correct in encoding_fixes.items(): result=result.replace(wrong,correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items(): result=re.sub(pattern,replacement,result)
    result=re.sub(r'([a-záéíóúñ])\1{2,}',r'\1',result,flags=re.IGNORECASE)
    result=re.sub(r'(?<=\.\s)([a-z])',lambda m:m.group(1).upper(),result)
    return result.strip()

def export_to_srt(data):
    srt=[]
    for i,seg in enumerate(data.segments,1):
        start=timedelta(seconds=seg['start']);end=timedelta(seconds=seg['end'])
        start_str=f"{start.seconds//3600:02}:{(start.seconds//60)%60:02}:{start.seconds%60:02},{start.microseconds//1000:03}"
        end_str=f"{end.seconds//3600:02}:{(end.seconds//60)%60:02}:{end.seconds%60:02},{end.microseconds//1000:03}"
        srt.append(f"{i}\n{start_str} --> {end_str}\n{seg['text'].strip()}\n")
    return "\n".join(srt)

# --- FUNCIONES DE CONVERSIÓN Y PROCESAMIENTO DE ARCHIVOS ---
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

# --- FUNCIONES DE ANÁLISIS ---
def generate_summary(text,client):
    try:
        completion=client.chat.completions.create(messages=[{"role":"system","content":"Eres un analista de noticias experto. Crea un resumen ejecutivo conciso en un solo párrafo. Regla estricta: NO incluyas frases introductorias. Comienza directamente con el contenido."},{"role":"user","content":f"Genera un resumen ejecutivo en un párrafo (máx 150 palabras) de la transcripción. Empieza directamente, sin preámbulos.\n\nTranscripción:\n{text}"}],model="llama-3.1-8b-instant",temperature=0.3,max_tokens=500)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def answer_question(question,text,client,history):
    try:
        messages=[{"role":"system","content":"Eres un asistente experto. Responde preguntas sobre la transcripción de manera precisa, basándote ÚNICAMENTE en su contenido. Si la información no está, indícalo claramente."}]
        for qa in history: messages.extend([{"role":"user","content":qa["question"]},{"role":"assistant","content":qa["answer"]}])
        messages.append({"role":"user","content":f"Transcripción:\n---\n{text}\n---\nPregunta: {question}\nResponde basándote solo en la transcripción."})
        completion=client.chat.completions.create(messages=messages,model="llama-3.1-8b-instant",temperature=0.2,max_tokens=800)
        return completion.choices[0].message.content
    except Exception as e: return f"Error al procesar la pregunta: {e}"

def extract_entities(text,client):
    try:
        completion=client.chat.completions.create(messages=[{"role":"system","content":'Analista de noticias de Colombia. Identifica personas, cargos y marcas. Devuelve un JSON con claves "people" (lista de objetos con "name","role") y "brands" (lista de strings). Si no encuentras nada, devuelve listas vacías.'},{"role":"user","content":f"Analiza esta transcripción y extrae entidades en el formato JSON especificado.\n\n{text}"}],model="llama-3.1-8b-instant",temperature=0.1,max_tokens=1500,response_format={"type":"json_object"})
        data=json.loads(completion.choices[0].message.content)
        return data.get("people",[]),data.get("brands",[])
    except Exception: return [],[]

def enrich_entities_with_timestamps(people,brands,segments):
    enriched_people,enriched_brands={},{}
    for person in people:
        name=person.get("name","").strip()
        if name and name not in enriched_people: enriched_people[name]={"details":person,"mentions":[]}
        for seg in segments:
            if name and re.search(r'\b'+re.escape(name)+r'\b',seg['text'],re.I): enriched_people[name]["mentions"].append({"start":seg['start'],"time":format_timestamp(seg['start']),"context":seg['text'].strip()})
    for brand in brands:
        name=brand.strip()
        if name and name not in enriched_brands: enriched_brands[name]={"mentions":[]}
        for seg in segments:
            if name and re.search(r'\b'+re.escape(name)+r'\b',seg['text'],re.I): enriched_brands[name]["mentions"].append({"start":seg['start'],"time":format_timestamp(seg['start']),"context":seg['text'].strip()})
    return enriched_people,enriched_brands

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")
with st.sidebar:
    st.header("⚙️ Configuración");model_option=st.selectbox("Modelo",["whisper-large-v3"]);language=st.selectbox("Idioma",["es"]);temperature=st.slider("Temperatura",0.0,1.0,0.0,0.1);st.markdown("---");st.subheader("🎯 Análisis Inteligente");enable_summary=st.checkbox("📝 Generar resumen",value=True);enable_entities=st.checkbox("👥 Extraer Entidades",value=True);st.markdown("---");st.subheader("🔍 Búsqueda");context_lines=st.slider("Líneas de contexto",1,5,2);st.markdown("---");st.subheader("🔧 Procesamiento")
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
            
            with st.spinner("🔄 Transcribiendo con IA..."):
                with open(tmp_path,"rb") as audio_file:
                    # --- PROMPT CORREGIDO Y SEGURO ---
                    prompt="Transcripción en español de Colombia. Palabras clave: autocrítica, política, República, Bogotá, qué, cómo, cuándo, por qué."
                    transcription=client.audio.transcriptions.create(file=(uploaded_file.name,audio_file.read()),model=model_option,temperature=temperature,language=language,response_format="verbose_json",prompt=prompt)
            os.unlink(tmp_path)

            text=fix_spanish_encoding(transcription.text)
            for seg in transcription.segments:seg['text']=fix_spanish_encoding(seg['text'])
            st.session_state.transcription,st.session_state.transcription_data=text,transcription

            with st.spinner("🧠 Generando análisis..."):
                if enable_summary:st.session_state.summary=generate_summary(text,client)
                if enable_entities:
                    people,brands=extract_entities(text,client)
                    st.session_state.people,st.session_state.brands=enrich_entities_with_timestamps(people,brands,transcription.segments)
            st.success("✅ ¡Proceso completado!");st.balloons()
        except Exception as e:st.error(f"❌ Error en la transcripción: {e}",icon="🔥")

if 'transcription' in st.session_state:
    st.markdown("---");st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes,start_time=st.session_state.audio_start_time)

    tab_titles=["📝 Transcripción","📊 Resumen Interactivo"];
    if st.session_state.get('people') or st.session_state.get('brands'):tab_titles.append("👥 Entidades Clave")
    tabs=st.tabs(tab_titles)

    with tabs[0]:
        c1, c2 = st.columns([4, 1]);
        with c1:
            search_query=st.text_input("🔎 Buscar:",value=st.session_state.last_search,key=f"search_{st.session_state.search_counter}")
            if search_query!=st.session_state.last_search:st.session_state.last_search=search_query;st.rerun()
        with c2:
            st.write("");
            if st.button("🗑️ Limpiar",use_container_width=True,disabled=not search_query):st.session_state.last_search="";st.session_state.search_counter+=1;st.rerun()
        
        if search_query:
            with st.expander("📍 Resultados de búsqueda", expanded=True):
                segments = st.session_state.transcription_data.segments; pattern = re.compile(re.escape(search_query), re.IGNORECASE); matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                if not matching_indices: st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)");
                    for i, match_idx in enumerate(matching_indices, 1):
                        # Simple context view
                        seg = segments[match_idx]
                        t_col, c_col = st.columns([0.15, 0.85]);
                        with t_col: t_col.button(f"▶️ {format_timestamp(seg['start'])}", key=f"play_{i}_{seg['start']}", on_click=set_audio_time, args=(seg['start'],), use_container_width=True)
                        with c_col:
                            text_html = pattern.sub(f"<span style='background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;'>\\g<0></span>", seg['text'])
                            st.markdown(f"<div style='background-color:#1e3a5f;padding:0.8rem;border-radius:6px;border-left:4px solid #fca311;color:#fff;'>{text_html}</div>", unsafe_allow_html=True)
                        if i < len(matching_indices): st.markdown("---")
        
        st.markdown("**📄 Transcripción completa:**"); text_html=st.session_state.transcription.replace('\n','<br>')
        if search_query: text_html=re.compile(re.escape(search_query), re.I).sub(f"<span style='background-color:#fca311;color:#14213d;padding:2px 5px;border-radius:4px;font-weight:bold;'>\\g<0></span>", text_html)
        st.markdown(f"<div style='background-color:#0E1117;color:#FAFAFA;border:1px solid #333;border-radius:10px;padding:1.5rem;max-height:500px;overflow-y:auto;font-family:\"Source Code Pro\",monospace;white-space:pre-wrap;'>{text_html}</div>", unsafe_allow_html=True);st.write("")
        d1,d2,d3,d4=st.columns([2,2,2,1.5]);
        d1.download_button("💾 TXT Simple",st.session_state.transcription.encode('utf-8'),"transcripcion.txt",use_container_width=True)
        d2.download_button("💾 TXT con Tiempos", "\n".join([f"[{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}] {s['text'].strip()}" for s in st.session_state.transcription_data.segments]).encode('utf-8'),"tiempos.txt",use_container_width=True)
        d3.download_button("💾 SRT Subtítulos",export_to_srt(st.session_state.transcription_data).encode('utf-8'),"subtitulos.srt",use_container_width=True)
        with d4: create_copy_button(st.session_state.transcription)

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
            if st.session_state.get('people'):
                st.markdown("### 👤 Personas y Cargos");
                for name, data in st.session_state.people.items():
                    st.markdown(f"**{name}** - *{data['details'].get('role', 'No especificado')}*")
                    if data['mentions']:
                        with st.expander(f"Ver {len(data['mentions'])} mención(es)"):
                            for m in data['mentions']:
                                c1,c2=st.columns([0.2,0.8]); c1.button(f"▶️ {m['time']}",key=f"p_{name}_{m['start']}",on_click=set_audio_time,args=(m['start'],)); c2.markdown(f"_{m['context']}_")
                st.markdown("---")
            if st.session_state.get('brands'):
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
st.markdown("""<div style='text-align: center; color: #666;'><p><strong>Transcriptor Pro - Johnascriptor - v3.8.0 (Whisper-large-v3 | Llama-3.1)</strong></p><p style='font-size: 0.85rem;'>✨ Versión estable con calidad de transcripción restaurada</p></div>""", unsafe_allow_html=True)
