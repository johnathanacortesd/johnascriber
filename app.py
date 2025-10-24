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
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA para noticias.</p>
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
if 'transcription_id' not in st.session_state:
    st.session_state.transcription_id = 0

# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = int(start_seconds)

try:
    api_key = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("❌ Error: No se encontró GROQ_API_KEY en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO DE CORRECCIONES AMPLIADO Y MEJORADO ---
SPANISH_WORD_CORRECTIONS = {
    # Correcciones generales de tildes y terminaciones
    r'\b([A-Za-z]+)ci(?!ón\b)\b': r'\1ción',
    r'\b([A-Za-z]+)cr(?!ítica\b)\b': r'\1crítica', # Mejora para "autocrítica"
    r'\b([A-Za-z]+)t(?!ico\b)\b': r'\1tico',
    r'\b([A-Za-z]+)g(?!ía\b)\b': r'\1gía',
    r'\b([A-Za-z]+)mic(?!a\b)\b': r'\1mica',
    
    # Palabras comunes
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    r'\bRepúblic(?!a\b)\b': 'República', r'\brepúblic(?!a\b)\b': 'república',
    r'\bBogot(?!á\b)\b': 'Bogotá',
    r'\bpolític(?!a\b)\b': 'política', r'\bPolític(?!a\b)\b': 'Política',
    r'\beconómic(?!a\b)\b': 'económica', r'\bEconómic(?!a\b)\b': 'Económica',
    r'\bAméric(?!a\b)\b': 'América',
    r'\badem(?!ás\b)\b': 'además', r'\bAdem(?!ás\b)\b': 'Además',
    r'\btambi(?!én\b)\b': 'también', r'\bTambi(?!én\b)\b': 'También',
    r'\búltim(?!o\b)\b': 'último', r'\bÚltim(?!o\b)\b': 'Último',
    
    # Preguntas y exclamaciones
    r'\b(P|p)or qu(?!é\b)\b': r'\1or qué', r'\b(Q|q)u(?!é\b)\b': r'\1ué',
    r'\b(C|c)ómo\b': r'\1ómo', r'\b(C|c)uándo\b': r'\1uándo', r'\b(D|d)ónde\b': r'\1ónde',
    r'\b(M|m)as\b': r'\1ás',
}

# --- FUNCIONES AUXILIARES ---

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    components.html(f"""
        <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">📋 Copiar Todo</button>
        <script>
        document.getElementById("{button_id}").onclick = function() {{
            const textArea = document.createElement("textarea");
            textArea.value = {text_json};
            textArea.style.position = "fixed"; textArea.style.top = "-9999px"; textArea.style.left = "-9999px";
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand("copy");
            document.body.removeChild(textArea);
            const button = document.getElementById("{button_id}");
            const originalText = button.innerText;
            button.innerText = "✅ ¡Copiado!";
            setTimeout(function() {{ button.innerText = originalText; }}, 2000);
        }};
        </script>""", height=40)

def format_timestamp(seconds):
    return str(timedelta(seconds=seconds)).split('.')[0].zfill(8)

def format_transcription_with_timestamps(data):
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos."
    lines = [f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}" for seg in data.segments]
    return "\n".join(lines)

def fix_spanish_encoding(text):
    if not text: return text
    result = text
    encoding_fixes = {'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ', 'Ã‘': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'}
    for wrong, correct in encoding_fixes.items(): result = result.replace(wrong, correct)
    for pattern, replacement in SPANISH_WORD_CORRECTIONS.items(): result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result, flags=re.IGNORECASE)
    result = re.sub(r'(?<=\.\s)([a-z])', lambda m: m.group(1).upper(), result)
    return result.strip()

# --- FUNCIONES DE CONVERSIÓN Y PROCESAMIENTO ---

def process_uploaded_file(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    original_size = len(file_bytes) / (1024 * 1024)
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()

    if file_extension in ['.mp4', '.mpeg', '.webm'] and MOVIEPY_AVAILABLE and original_size > 25:
        with st.spinner(f"🎬 Video detectado ({original_size:.2f} MB). Convirtiendo a audio..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_video:
                tmp_video.write(file_bytes)
                video_path = tmp_video.name
            
            audio_path = video_path + '.mp3'
            try:
                video = VideoFileClip(video_path)
                video.audio.write_audiofile(audio_path, codec='mp3', bitrate='128k', verbose=False, logger=None)
                video.close()
                with open(audio_path, 'rb') as f:
                    file_bytes = f.read()
                st.success(f"✅ Conversión a audio completada: {original_size:.2f} MB → {len(file_bytes) / (1024 * 1024):.2f} MB")
            except Exception as e:
                st.warning(f"⚠️ No se pudo convertir el video a audio. Se intentará transcribir directamente. Error: {e}")
            finally:
                if os.path.exists(video_path): os.unlink(video_path)
                if os.path.exists(audio_path): os.unlink(audio_path)
    
    return file_bytes

# --- FUNCIONES DE ANÁLISIS CON IA ---

def generate_summary(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Eres un analista de noticias experto. Tu tarea es crear un resumen ejecutivo, conciso y profesional en un solo párrafo, utilizando español correcto con todas sus tildes."},
                {"role": "user", "content": f"Basado en la siguiente transcripción, genera un resumen ejecutivo en un párrafo (máximo 150 palabras). Ve directo al grano, sin frases introductorias.\n\nTranscripción:\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.3, max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e: return f"Error al generar resumen: {e}"

def extract_entities(transcription_text, client):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": """Eres un analista experto en noticias de Colombia. Tu tarea es identificar personas, sus cargos y marcas mencionadas en una transcripción. Devuelve un objeto JSON con dos claves: "people" y "brands".
- "people": una lista de objetos, cada uno con "name", "role" y "context" (la frase exacta). Si el rol no se menciona, usa "No especificado".
- "brands": una lista de objetos, cada uno con "name" y "context".
Asegúrate de que el JSON sea válido."""},
                {"role": "user", "content": f"Analiza esta transcripción y extrae las personas, cargos y marcas. Formatea la salida como el JSON especificado.\n\nTranscripción:\n{transcription_text}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.1, max_tokens=1500, response_format={"type": "json_object"}
        )
        response_content = chat_completion.choices[0].message.content
        data = json.loads(response_content)
        return data.get("people", []), data.get("brands", [])
    except (json.JSONDecodeError, KeyError) as e:
        return [{"name": "Error de Análisis", "role": "La IA no devolvió un JSON válido.", "context": str(e)}], []
    except Exception as e:
        return [{"name": "Error de API", "role": str(e), "context": "No se pudo contactar al servicio de análisis."}], []

def enrich_entities_with_timestamps(entities, segments):
    enriched_entities = {}
    for entity in entities:
        entity_name = entity.get("name", "Desconocido")
        context_sentence = entity.get("context", "")
        
        if entity_name not in enriched_entities:
            enriched_entities[entity_name] = {"details": entity, "mentions": []}

        found_mention = False
        for segment in segments:
            if context_sentence in segment['text']:
                enriched_entities[entity_name]["mentions"].append({
                    "start": segment['start'],
                    "time": format_timestamp(segment['start']),
                    "context": context_sentence
                })
                found_mention = True
                break
        
        if not found_mention:
             # Fallback: search for name if context fails
            for segment in segments:
                if entity_name in segment['text']:
                    enriched_entities[entity_name]["mentions"].append({
                        "start": segment['start'],
                        "time": format_timestamp(segment['start']),
                        "context": segment['text'].strip()
                    })
                    break
    return enriched_entities

# --- INTERFAZ DE LA APP ---
st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración"); model_option = st.selectbox("Modelo de Transcripción", ["whisper-large-v3"], index=0, help="Máxima precisión para español."); language = st.selectbox("Idioma", ["es"], index=0, help="Español para máxima calidad de corrección."); temperature = st.slider("Temperatura", 0.0, 1.0, 0.0, 0.1, help="0.0 para máxima precisión"); st.markdown("---"); st.subheader("🎯 Análisis Inteligente"); enable_summary = st.checkbox("📝 Generar resumen automático", value=True); enable_entities = st.checkbox("👥 Extraer personas y marcas", value=True); st.markdown("---"); st.subheader("🔍 Búsqueda Contextual"); context_lines = st.slider("Líneas de contexto", 1, 5, 2); st.markdown("---"); 
    if MOVIEPY_AVAILABLE: st.info("💡 Videos > 25 MB se convertirán a audio.");
    else: st.warning("⚠️ MoviePy no disponible para conversión de video.");
    st.markdown("---"); st.success("✅ API Key configurada.")

st.subheader("📤 Sube tu archivo de audio o video")
uploaded_file = st.file_uploader("Selecciona un archivo", type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"], label_visibility="collapsed")

if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
    st.session_state.clear(); st.session_state['password_correct'] = True # Mantener la sesión
    st.session_state.audio_start_time = 0; st.session_state.transcription_id = st.session_state.get('transcription_id', 0) + 1
    
    file_bytes = process_uploaded_file(uploaded_file)
    st.session_state.uploaded_audio_bytes = file_bytes
    
    try:
        client = Groq(api_key=api_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
            tmp.write(file_bytes); tmp_path = tmp.name
        
        with st.spinner("🔄 Transcribiendo con IA... (puede tardar unos minutos)"):
            with open(tmp_path, "rb") as audio_file:
                # --- PROMPT MEJORADO Y ENFOCADO ---
                spanish_prompt = (
                    "Este es un noticiero de Colombia. Transcribe con la máxima precisión posible en español colombiano. "
                    "Reglas estrictas: 1. NUNCA cortes palabras, especialmente las que llevan tilde como 'política', 'económica', 'República', 'autocrítica'. Escríbelas completas. "
                    "2. Pon especial atención a las tildes en preguntas (qué, cómo, cuándo) y en palabras como 'sí' (afirmación), 'más' (cantidad), 'está' (verbo). "
                    "3. Mantén la puntuación original (comas, puntos, ¿?, ¡!). "
                    "4. Transcribe nombres propios y acrónimos fielmente. "
                    "El resultado debe ser una transcripción textual y profesional, lista para ser publicada."
                )
                transcription = client.audio.transcriptions.create(
                    file=(uploaded_file.name, audio_file.read()), model=model_option,
                    temperature=temperature, language=language, response_format="verbose_json", prompt=spanish_prompt
                )
        os.unlink(tmp_path)
        
        with st.spinner("✨ Aplicando correcciones y mejoras..."):
            transcription_text = fix_spanish_encoding(transcription.text)
            for segment in transcription.segments:
                segment['text'] = fix_spanish_encoding(segment['text'])
        
        st.session_state.transcription = transcription_text
        st.session_state.transcription_data = transcription
        
        with st.spinner("🧠 Generando análisis inteligente..."):
            if enable_summary: st.session_state.summary = generate_summary(transcription_text, client)
            if enable_entities:
                people, brands = extract_entities(transcription_text, client)
                st.session_state.people = enrich_entities_with_timestamps(people, transcription.segments)
                st.session_state.brands = enrich_entities_with_timestamps(brands, transcription.segments)

        st.success("✅ ¡Transcripción y análisis completados!"); st.balloons()
    except Exception as e:
        st.error(f"❌ Error durante la transcripción: {e}")

if 'transcription' in st.session_state:
    st.markdown("---"); st.subheader("🎧 Reproduce y Analiza el Contenido")
    st.audio(st.session_state.uploaded_audio_bytes, start_time=st.session_state.audio_start_time)

    tab_titles = ["📝 Transcripción Completa", "📊 Resumen Interactivo"]
    if 'people' in st.session_state or 'brands' in st.session_state:
        tab_titles.append("👥 Entidades Clave")
    tabs = st.tabs(tab_titles)

    with tabs[0]:
        st.markdown("**📄 Transcripción:**")
        # --- MEJORA: Se añade una clave única para resetear el scroll ---
        transcription_html = st.session_state.transcription.replace('\n', '<br>')
        st.markdown(f"""
            <div style="background-color: #0E1117; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; line-height: 1.7; white-space: pre-wrap;"
            key="transcription_box_{st.session_state.transcription_id}">
            {transcription_html}
            </div>""", unsafe_allow_html=True)
        st.write("")
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1: st.download_button("💾 Descargar (.txt)", st.session_state.transcription.encode('utf-8'), "transcripcion.txt", use_container_width=True)
        with col_d2: st.download_button("💾 TXT con Tiempos", format_transcription_with_timestamps(st.session_state.transcription_data).encode('utf-8'), "transcripcion_tiempos.txt", use_container_width=True)
        with col_d3: create_copy_button(st.session_state.transcription)

    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
        else:
            st.info("El resumen no fue generado. Activa la opción en el sidebar.")

    if len(tabs) > 2:
        with tabs[2]:
            if 'people' in st.session_state and st.session_state.people:
                st.markdown("### 👤 Personas y Cargos")
                for name, data in st.session_state.people.items():
                    st.markdown(f"**{name}** - *{data['details'].get('role', 'No especificado')}*")
                    with st.expander(f"Ver {len(data['mentions'])} mención(es) en el audio"):
                        for mention in data['mentions']:
                            col1, col2 = st.columns([0.2, 0.8])
                            with col1:
                                st.button(f"▶️ {mention['time']}", key=f"play_{name}_{mention['start']}", on_click=set_audio_time, args=(mention['start'],))
                            with col2:
                                st.markdown(f"_{mention['context']}_")
                st.markdown("---")

            if 'brands' in st.session_state and st.session_state.brands:
                st.markdown("### 🏢 Marcas Mencionadas")
                for name, data in st.session_state.brands.items():
                    st.markdown(f"**{name}**")
                    with st.expander(f"Ver {len(data['mentions'])} mención(es) en el audio"):
                        for mention in data['mentions']:
                            col1, col2 = st.columns([0.2, 0.8])
                            with col1:
                                st.button(f"▶️ {mention['time']}", key=f"play_brand_{name}_{mention['start']}", on_click=set_audio_time, args=(mention['start'],))
                            with col2:
                                st.markdown(f"_{mention['context']}_")
            
            if not st.session_state.get('people') and not st.session_state.get('brands'):
                 st.info("No se identificaron personas o marcas clave. Activa la opción en el sidebar.")


    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
        password_status = st.session_state.password_correct
        st.session_state.clear()
        st.session_state.password_correct = password_status
        st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'>
<p><strong>Transcriptor Pro - Johnascriptor - v3.3.0 (Whisper-large-v3 | Llama-3.1)</strong></p>
<p style='font-size: 0.85rem;'>✨ Optimizado para noticias en español de Colombia</p>
</div>""", unsafe_allow_html=True)
