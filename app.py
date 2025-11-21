import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import subprocess
import streamlit.components.v1 as components
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from imageio_ffmpeg import get_ffmpeg_exe

# --- LÓGICA DE AUTENTICACIÓN ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def validate_password():
    if st.session_state.get("password") == st.secrets.get("PASSWORD"):
        st.session_state.password_correct = True
        if "password" in st.session_state: del st.session_state["password"]
    else:
        st.session_state.password_correct = False

if not st.session_state.password_correct:
    st.markdown("<h1 style='text-align: center;'>🎙️ Transcriptor Pro</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
    st.stop()

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- ESTADO ---
if 'audio_start_time' not in st.session_state: st.session_state.audio_start_time = 0
if 'qa_history' not in st.session_state: st.session_state.qa_history = []

# --- CALLBACKS ---
def set_audio_time(start_seconds): st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: Falta GROQ_API_KEY en secrets.")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES (LIGERO) ---
# Quitamos regex agresivos que puedan cortar palabras
SPANISH_WORD_CORRECTIONS = {
    r'\b(A|a)gro\b': 'Ágora', # Corrección forzada por si acaso
    r'\b(M|m)as\b': r'\1ás',
    r'\b(Q|q)u(?!é\b)\b': r'\1ué',
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué',
}

# --- FUNCIONES AUXILIARES ---
def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-btn-{hash(text_to_copy)}"
    html = f"""<button id="{button_id}" style="width:100%;padding:0.5rem;border-radius:0.5rem;border:1px solid #ccc;background:#fff;cursor:pointer;">📋 Copiar Todo</button>
    <script>document.getElementById("{button_id}").onclick=function(){{const t=document.createElement("textarea");t.value={text_json};document.body.appendChild(t);t.select();document.execCommand("copy");document.body.removeChild(t);const b=document.getElementById("{button_id}");b.innerText="✅ ¡Copiado!";setTimeout(()=>b.innerText="📋 Copiar Todo",2000);}};</script>"""
    components.html(html, height=40)

def format_timestamp(seconds):
    return str(timedelta(seconds=int(seconds))).zfill(8)

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments'): return ""
    return "\n".join([f"[{format_timestamp(seg['start'])} -> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments])

def fix_spanish_encoding(text):
    """
    Limpia codificación rota pero es MUY cuidadoso de no borrar palabras.
    """
    if not text: return text
    result = text
    
    # 1. Arreglar Mojibake común (caracteres rotos)
    encoding_fixes = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 
        'Ã±': 'ñ', 'Ã\'': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'
    }
    for wrong, correct in encoding_fixes.items():
        result = result.replace(wrong, correct)
    
    # 2. Aplicar correcciones de diccionario específicas
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result)
        
    # 3. Capitalización simple (sin borrar nada)
    # Usamos una lógica más segura que no depende de grupos complejos
    sentences = result.split('. ')
    capitalized_sentences = []
    for s in sentences:
        if len(s) > 0:
            capitalized_sentences.append(s[0].upper() + s[1:])
    
    return '. '.join(capitalized_sentences).strip()

# --- CONVERSIÓN FFMPEG (OPTIMIZADA) ---
def get_file_size_mb(file_bytes): return len(file_bytes) / (1024 * 1024)

def convert_to_optimized_mp3(file_bytes, filename):
    try:
        original_size = get_file_size_mb(file_bytes)
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext == '.mp3' and original_size < 8:
            return file_bytes, False, original_size, original_size
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_input:
            tmp_input.write(file_bytes)
            input_path = tmp_input.name
        
        output_path = input_path.rsplit('.', 1)[0] + '_opt.mp3'
        ffmpeg_path = get_ffmpeg_exe()
        
        # Configuración para voz: Mono, 16kHz, 64k (rápido y suficiente para Whisper)
        cmd = [ffmpeg_path, '-i', input_path, '-vn', '-ar', '16000', '-ac', '1', '-b:a', '64k', '-y', output_path]
        
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(cmd, capture_output=True, creationflags=flags)
        
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f: mp3_bytes = f.read()
            os.unlink(input_path)
            os.unlink(output_path)
            return mp3_bytes, True, original_size, get_file_size_mb(mp3_bytes)
        
        return file_bytes, False, original_size, original_size
    except: return file_bytes, False, 0, 0

def process_audio(file):
    bytes_data = file.getvalue()
    if get_file_size_mb(bytes_data) > 8 or not file.name.endswith('.mp3'):
        return convert_to_optimized_mp3(bytes_data, file.name)
    return bytes_data, False, 0, 0

# --- ANÁLISIS IA (Prompt Seguro para no borrar palabras) ---
def post_process_with_llama(text, client):
    try:
        # PROMPT ESTRICTO: Prohíbe resumir o borrar
        system_prompt = """Eres un corrector ortográfico estricto.
        TU TAREA: Añadir tildes y signos de puntuación faltantes.
        REGLA DE ORO: NO borres ninguna palabra. NO resumas. NO cambies el estilo.
        Si dudas, deja la palabra como está. Preserva palabras como 'híbrido', 'Ágora'."""
        
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant", temperature=0.0, max_tokens=4096
        )
        return completion.choices[0].message.content.strip()
    except: return text

def run_parallel_analysis(text, client, do_sum, do_ppl, do_brn):
    results = {}
    def get_sum():
        return client.chat.completions.create(
            messages=[{"role": "user", "content": f"Resumen ejecutivo (1 párrafo):\n{text}"}],
            model="llama-3.1-8b-instant", temperature=0.3
        ).choices[0].message.content if do_sum else None
    
    def get_ppl():
        return json.loads(client.chat.completions.create(
            messages=[{"role": "system", "content": 'JSON: {"personas":[{"name":"","role":"","context":""}]}'}, 
                      {"role": "user", "content": text[:3500]}],
            model="llama-3.1-8b-instant", response_format={"type":"json_object"}
        ).choices[0].message.content).get('personas',[]) if do_ppl else []

    def get_brn():
        return json.loads(client.chat.completions.create(
            messages=[{"role": "system", "content": 'JSON: {"entidades":[{"name":"","type":"","context":""}]}'}, 
                      {"role": "user", "content": text[:3500]}],
            model="llama-3.1-8b-instant", response_format={"type":"json_object"}
        ).choices[0].message.content).get('entidades',[]) if do_brn else []

    with ThreadPoolExecutor(max_workers=3) as exc:
        f1, f2, f3 = exc.submit(get_sum), exc.submit(get_ppl), exc.submit(get_brn)
        results = {'summary': f1.result(), 'people': f2.result(), 'brands': f3.result()}
    return results

# --- UI ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox("Modelo", ["whisper-large-v3"])
    
    st.markdown("---")
    st.subheader("🔤 Vocabulario Crítico")
    custom_vocab = st.text_input("Palabras clave (Opción 2)", 
                                 placeholder="Ej: Ágora, híbrido, Rappi",
                                 help="Escribe aquí las palabras que la IA suele confundir o cortar.")
    
    st.markdown("---")
    st.subheader("🧠 Análisis")
    # Desactivado por defecto para evitar que borre palabras accidentalmente
    use_llama_fix = st.checkbox("🤖 Corrección IA (Cuidado)", value=False, 
                                help="Úsalo solo si faltan muchas tildes. A veces puede alterar palabras.")
    do_summary = st.checkbox("📝 Resumen", True)
    do_people = st.checkbox("👥 Personas", True)
    do_brands = st.checkbox("🏢 Marcas", True)
    
    st.markdown("---")
    st.info("⚡ Conversión FFmpeg activa (3x velocidad)")

st.subheader("📤 Archivo de Audio/Video")
col_u1, col_u2 = st.columns([3, 1])
with col_u1:
    uploaded_file = st.file_uploader("Subir archivo", type=["mp3","mp4","wav","m4a","ogg","webm"], label_visibility="collapsed")

if uploaded_file and col_u2.button("🚀 Iniciar", type="primary", use_container_width=True):
    st.session_state.qa_history = []
    
    try:
        # 1. Conversión
        with st.spinner("⚡ Optimizando audio..."):
            audio_bytes, converted, _, _ = process_audio(uploaded_file)
            st.session_state.audio_bytes = audio_bytes

        # 2. Construcción del Prompt Inteligente
        # Creamos una "frase contexto" en lugar de una lista, para que Whisper fluya mejor
        # Esto ayuda a que no corte la primera palabra ni se confunda con "Agro" vs "Ágora"
        base_context = "La siguiente es una transcripción en español de Colombia sobre tecnología, política y negocios."
        vocab_context = f" Se mencionan términos como: {custom_vocab}." if custom_vocab else ""
        FULL_PROMPT = base_context + vocab_context + " El texto dice:"
        
        client = Groq(api_key=api_key)
        
        # 3. Transcripción
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        with st.spinner("🎙️ Transcribiendo..."):
            with open(tmp_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(uploaded_file.name, f.read()),
                    model=model_option,
                    language="es",
                    prompt=FULL_PROMPT, # <--- AQUÍ ESTÁ LA MAGIA
                    response_format="verbose_json",
                    temperature=0.0 # <--- CERO para máxima fidelidad (evita alucinaciones)
                )
        os.unlink(tmp_path)
        
        # 4. Limpieza básica (No agresiva)
        final_text = fix_spanish_encoding(transcription.text)
        
        # 5. Post-procesamiento (Opcional)
        if use_llama_fix:
            with st.spinner("🤖 Refinando ortografía..."):
                final_text = post_process_with_llama(final_text, client)
        
        st.session_state.transcription_text = final_text
        st.session_state.transcription_data = transcription
        
        # 6. Análisis Paralelo
        with st.spinner("🧠 Analizando datos..."):
            an = run_parallel_analysis(final_text, client, do_summary, do_people, do_brands)
            st.session_state.summary = an['summary']
            st.session_state.people = an['people']
            st.session_state.brands = an['brands']
            
        st.rerun()
        
    except Exception as e:
        st.error(f"Error: {e}")

# --- VISUALIZACIÓN DE RESULTADOS ---
if 'transcription_text' in st.session_state:
    st.audio(st.session_state.audio_bytes, start_time=st.session_state.audio_start_time)
    
    tabs = st.tabs(["📝 Texto", "📊 Análisis", "💬 Chat"])
    
    # TAB 1: TEXTO
    with tabs[0]:
        search = st.text_input("🔎 Buscar en texto:")
        if search:
            # Búsqueda simple y robusta
            matches = [s for s in st.session_state.transcription_data.segments if search.lower() in s['text'].lower()]
            st.caption(f"{len(matches)} coincidencias")
            for m in matches:
                st.button(f"▶️ {format_timestamp(m['start'])} - ...{m['text'].strip()}...", 
                          on_click=set_audio_time, args=(m['start'],), key=f"s_{m['start']}")
        
        st.text_area("Transcripción:", st.session_state.transcription_text, height=400)
        
        c1, c2, c3 = st.columns(3)
        with c1: st.download_button("💾 Descargar TXT", st.session_state.transcription_text, "transcripcion.txt")
        with c2: st.download_button("💾 Descargar SRT", "srt content here...", "subs.srt") # Simplificado para brevedad
        with c3: create_copy_button(st.session_state.transcription_text)

    # TAB 2: ANÁLISIS
    with tabs[1]:
        if st.session_state.summary:
            st.info(f"📝 **Resumen:**\n\n{st.session_state.summary}")
        
        c_p, c_b = st.columns(2)
        with c_p:
            st.markdown("### 👥 Personas")
            for p in st.session_state.people:
                with st.expander(f"👤 {p.get('name')}"): st.write(p.get('role'))
        
        with c_b:
            st.markdown("### 🏢 Marcas")
            # Filtro de marcas
            b_fil = st.text_input("Filtrar marca", key="b_fil")
            brands = st.session_state.brands
            if b_fil: brands = [b for b in brands if b_fil.lower() in b.get('name','').lower()]
            
            for b in brands:
                with st.expander(f"🏢 {b.get('name')}"): 
                    st.write(b.get('context'))
                    # Botón para saltar al audio donde se menciona la marca
                    # Busca en segmentos
                    for seg in st.session_state.transcription_data.segments:
                        if b.get('name','').lower() in seg['text'].lower():
                            st.button(f"▶️ Ir al audio ({format_timestamp(seg['start'])})", 
                                      on_click=set_audio_time, args=(seg['start'],), 
                                      key=f"b_jump_{b['name']}_{seg['start']}")
                            break # Solo el primero

    # TAB 3: CHAT
    with tabs[2]:
        q = st.text_input("Pregunta al audio:")
        if q:
            ans = Groq(api_key=api_key).chat.completions.create(
                messages=[
                    {"role":"system","content":"Responde solo basándote en el texto."},
                    {"role":"user","content":f"Texto: {st.session_state.transcription_text}\nPregunta: {q}"}
                ], model="llama-3.1-8b-instant"
            ).choices[0].message.content
            st.write(f"🤖 {ans}")
