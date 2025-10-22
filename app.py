import streamlit as st
from groq import Groq
import tempfile
import os
import json
import re
import streamlit.components.v1 as components
from datetime import timedelta
from collections import Counter
import traceback

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
        <p style='color: #666; margin-bottom: 2rem;'>Análisis avanzado de audio con IA</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True, disabled=not uploaded_file):
        # Reiniciar estados
        st.session_state.audio_start_time = 0
        st.session_state.audio_player_key = 0
        st.session_state.last_search = ""
        st.session_state.search_counter = st.session_state.get('search_counter', 0) + 1
        st.session_state.qa_history = []
        
        with st.spinner("🔄 Procesando archivo..."):
            try:
                file_bytes = uploaded_file.getvalue()
                original_size = get_file_size_mb(file_bytes)
                is_video = os.path.splitext(uploaded_file.name)[1].lower() in ['.mp4', '.mpeg', '.webm']
                
                # Convertir video a audio si es necesario
                if is_video and MOVIEPY_AVAILABLE and original_size > 25:
                    with st.spinner(f"🎬 Video de {original_size:.2f} MB. Convirtiendo a audio..."):
                        file_bytes, converted = convert_video_to_audio(file_bytes, uploaded_file.name)
                        if converted:
                            new_size = get_file_size_mb(file_bytes)
                            st.success(f"✅ Convertido: {original_size:.2f} MB → {new_size:.2f} MB")
                
                # Comprimir audio si está habilitado
                if MOVIEPY_AVAILABLE and compress_audio_option:
                    with st.spinner("📦 Comprimiendo audio..."):
                        size_before = get_file_size_mb(file_bytes)
                        file_bytes = compress_audio(file_bytes, uploaded_file.name)
                        st.success(f"✅ Comprimido: {size_before:.2f} MB → {get_file_size_mb(file_bytes):.2f} MB")
                
                st.session_state.uploaded_audio_bytes = file_bytes
                
                # Crear cliente de Groq
                client = Groq(api_key=api_key)
                
                # Crear archivo temporal para la transcripción
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(file_bytes)
                    tmp_file_path = tmp.name
                
                # Realizar transcripción
                with st.spinner("🔄 Transcribiendo con IA... (puede tardar unos minutos)"):
                    with open(tmp_file_path, "rb") as audio_file:
                        spanish_prompt = """Transcribe cuidadosamente en español. Asegura que todas las palabras estén completas y con sus acentos correctos. Presta especial atención a: qué, por qué, sí, está, más, él. Completa palabras como: fundación, información, situación, declaración, compañía, economía, miércoles, sostenible, documental."""
                        
                        transcription = client.audio.transcriptions.create(
                            file=(uploaded_file.name, audio_file.read()),
                            model=model_option,
                            temperature=temperature,
                            language=language,
                            response_format="verbose_json",
                            prompt=spanish_prompt if language == "es" else None
                        )
                
                # Limpiar archivo temporal
                try:
                    os.unlink(tmp_file_path)
                except:
                    pass
                
                # Aplicar correcciones si está habilitado
                transcription_text = transcription.text
                if enable_tilde_fix and language == "es":
                    with st.spinner("✨ Aplicando correcciones de tildes..."):
                        transcription_text = fix_spanish_encoding(transcription.text)
                        if hasattr(transcription, 'segments'):
                            for segment in transcription.segments:
                                segment['text'] = fix_spanish_encoding(segment['text'])
                        quality_issues = check_transcription_quality(transcription_text)
                        for issue in quality_issues:
                            st.info(issue)
                
                # Guardar transcripción en el estado
                st.session_state.transcription = transcription_text
                st.session_state.transcription_data = transcription
                
                # Generar análisis inteligente
                with st.spinner("🧠 Generando análisis inteligente..."):
                    if enable_summary:
                        st.session_state.summary = generate_summary(transcription_text, client)
                    if enable_quotes:
                        st.session_state.quotes = extract_quotes(transcription.segments)
                    if enable_people:
                        st.session_state.people = extract_people_and_roles(transcription_text, client)
                
                st.success("✅ ¡Transcripción y análisis completados!")
                st.balloons()
                
            except Exception as e:
                st.error(f"❌ Error durante la transcripción: {str(e)}")
                st.error(f"Detalles técnicos: {traceback.format_exc()}")

# --- MOSTRAR RESULTADOS ---
if 'transcription' in st.session_state and 'uploaded_audio_bytes' in st.session_state:
    st.markdown("---")
    st.subheader("🎧 Reproduce y Analiza el Contenido")
    
    # Reproductor de audio con key dinámica
    st.audio(
        st.session_state.uploaded_audio_bytes,
        start_time=st.session_state.audio_start_time,
        key=f"audio_player_{st.session_state.audio_player_key}"
    )
    
    # PESTAÑAS PRINCIPALES
    tab_titles = ["📝 Transcripción", "📊 Resumen Interactivo", "💬 Citas y Declaraciones"]
    if 'people' in st.session_state and st.session_state.people:
        tab_titles.append("👥 Personas Clave")
        
    tabs = st.tabs(tab_titles)
    
    # ===== PESTAÑA 1: TRANSCRIPCIÓN MEJORADA =====
    with tabs[0]:
        HIGHLIGHT_STYLE = "background-color: #fca311; color: #14213d; padding: 2px 5px; border-radius: 4px; font-weight: bold;"
        MATCH_LINE_STYLE = "background-color: #1e3a5f; padding: 0.8rem; border-radius: 6px; border-left: 4px solid #fca311; color: #ffffff; font-size: 1rem; line-height: 1.6;"
        CONTEXT_LINE_STYLE = "background-color: #1a1a1a; padding: 0.6rem; border-radius: 4px; color: #b8b8b8; font-size: 0.92rem; line-height: 1.5; border-left: 2px solid #404040;"
        TRANSCRIPTION_BOX_STYLE = "background-color: #0E1117; color: #FAFAFA; border: 1px solid #333; border-radius: 10px; padding: 1.5rem; max-height: 500px; overflow-y: auto; font-family: 'Source Code Pro', monospace; line-height: 1.7; white-space: pre-wrap; font-size: 0.95rem;"

        col_search1, col_search2 = st.columns([4, 1])
        with col_search1:
            search_query = st.text_input(
                "🔎 Buscar en la transcripción:",
                value=st.session_state.get('last_search', ''),
                key=f"search_input_{st.session_state.get('search_counter', 0)}"
            )
            if search_query != st.session_state.get('last_search', ''):
                st.session_state.last_search = search_query
        with col_search2:
            st.write("")
            if st.button("🗑️ Limpiar", use_container_width=True, disabled=not search_query):
                st.session_state.last_search = ""
                st.session_state.search_counter += 1
                st.rerun()
        
        # Búsqueda contextual
        if search_query:
            with st.expander("📍 Resultados de búsqueda con contexto extendido", expanded=True):
                segments = st.session_state.transcription_data.segments
                pattern = re.compile(re.escape(search_query), re.IGNORECASE)
                matching_indices = [i for i, seg in enumerate(segments) if pattern.search(seg['text'])]
                
                if not matching_indices:
                    st.info("❌ No se encontraron coincidencias.")
                else:
                    st.success(f"✅ {len(matching_indices)} coincidencia(s) encontrada(s)")
                    st.caption(f"📊 Mostrando {context_lines} línea(s) de contexto antes y después de cada resultado")
                    
                    for result_num, match_idx in enumerate(matching_indices, 1):
                        st.markdown(f"### 🎯 Resultado {result_num} de {len(matching_indices)}")
                        
                        context_segments = get_extended_context(segments, match_idx, context_lines)
                        
                        for ctx_seg in context_segments:
                            col_time, col_content = st.columns([0.15, 0.85])
                            
                            with col_time:
                                st.button(
                                    f"▶️ {ctx_seg['time']}",
                                    key=f"play_ctx_{result_num}_{ctx_seg['start']}",
                                    on_click=set_audio_time,
                                    args=(int(ctx_seg['start']),),
                                    use_container_width=True
                                )
                            
                            with col_content:
                                if ctx_seg['is_match']:
                                    highlighted_text = pattern.sub(
                                        f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>',
                                        ctx_seg['text']
                                    )
                                    st.markdown(
                                        f"<div style='{MATCH_LINE_STYLE}'><strong>🎯 </strong>{highlighted_text}</div>",
                                        unsafe_allow_html=True
                                    )
                                else:
                                    st.markdown(
                                        f"<div style='{CONTEXT_LINE_STYLE}'>{ctx_seg['text']}</div>",
                                        unsafe_allow_html=True
                                    )
                        
                        if result_num < len(matching_indices):
                            st.markdown("---")

        # Transcripción completa
        st.markdown("**📄 Transcripción completa:**")
        transcription_html = st.session_state.transcription.replace('\n', '<br>')
        if search_query:
            pattern = re.compile(re.escape(search_query), re.IGNORECASE)
            transcription_html = pattern.sub(
                f'<span style="{HIGHLIGHT_STYLE}">\\g<0></span>',
                transcription_html
            )
        st.markdown(
            f'<div style="{TRANSCRIPTION_BOX_STYLE}">{transcription_html}</div>',
            unsafe_allow_html=True
        )

        st.write("")
        col_d1, col_d2, col_d3, col_d4 = st.columns([2, 2, 2, 1.5])
        with col_d1:
            st.download_button(
                "💾 Descargar TXT Simple",
                st.session_state.transcription.encode('utf-8'),
                "transcripcion.txt",
                "text/plain; charset=utf-8",
                use_container_width=True
            )
        with col_d2:
            st.download_button(
                "💾 TXT con Tiempos",
                format_transcription_with_timestamps(st.session_state.transcription_data).encode('utf-8'),
                "transcripcion_tiempos.txt",
                "text/plain; charset=utf-8",
                use_container_width=True
            )
        with col_d3:
            st.download_button(
                "💾 SRT Subtítulos",
                export_to_srt(st.session_state.transcription_data).encode('utf-8'),
                "subtitulos.srt",
                "application/x-subrip; charset=utf-8",
                use_container_width=True
            )
        with col_d4:
            create_copy_button(st.session_state.transcription)
    
    # ===== PESTAÑA 2: RESUMEN INTERACTIVO CON Q&A =====
    with tabs[1]:
        if 'summary' in st.session_state:
            st.markdown("### 📝 Resumen Ejecutivo")
            st.markdown(st.session_state.summary)
            
            st.write("")
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                st.download_button(
                    "💾 Descargar Resumen",
                    st.session_state.summary.encode('utf-8'),
                    "resumen.txt",
                    "text/plain; charset=utf-8",
                    use_container_width=True
                )
            with col_s2:
                create_copy_button(st.session_state.summary)
            
            st.markdown("---")
            st.markdown("### 💭 Haz preguntas sobre el contenido")
            st.caption("Pregunta lo que quieras sobre la transcripción y obtén respuestas basadas en el contenido")
            
            if 'qa_history' not in st.session_state:
                st.session_state.qa_history = []
            
            # Mostrar historial
            if st.session_state.qa_history:
                st.markdown("#### 📚 Historial de conversación")
                for i, qa in enumerate(st.session_state.qa_history):
                    with st.container():
                        st.markdown(f"**🙋 Pregunta {i+1}:** {qa['question']}")
                        st.markdown(f"**🤖 Respuesta:** {qa['answer']}")
                        st.markdown("---")
            
            # Formulario para nuevas preguntas
            with st.form(key="question_form", clear_on_submit=True):
                user_question = st.text_area(
                    "Escribe tu pregunta aquí:",
                    placeholder="Ejemplo: ¿Cuáles son los puntos principales mencionados?\n¿Qué opinión expresó [persona]?\n¿Se mencionó algo sobre [tema]?",
                    height=100
                )
                col_q1, col_q2, col_q3 = st.columns([2, 2, 1])
                with col_q1:
                    submit_question = st.form_submit_button("🚀 Enviar Pregunta", use_container_width=True)
                with col_q2:
                    clear_history = st.form_submit_button("🗑️ Borrar Historial", use_container_width=True)
            
            if submit_question and user_question.strip():
                with st.spinner("🤔 Analizando la transcripción..."):
                    try:
                        client = Groq(api_key=api_key)
                        answer = answer_question(
                            user_question,
                            st.session_state.transcription,
                            client,
                            st.session_state.qa_history
                        )
                        st.session_state.qa_history.append({
                            'question': user_question,
                            'answer': answer
                        })
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al procesar la pregunta: {str(e)}")
            
            if clear_history:
                st.session_state.qa_history = []
                st.rerun()
        else:
            st.info("📝 El resumen no fue generado. Activa la opción en el sidebar y vuelve a transcribir.")
    
    # ===== PESTAÑA 3: CITAS Y DECLARACIONES =====
    with tabs[2]:
        if 'quotes' in st.session_state and st.session_state.quotes:
            st.markdown("### 💬 Citas y Declaraciones Relevantes")
            st.caption(f"Se encontraron {len(st.session_state.quotes)} citas y declaraciones importantes.")
            
            for idx, quote in enumerate(st.session_state.quotes):
                type_badge = "🗣️ **Cita Textual**" if quote['type'] == 'quote' else "📢 **Declaración**"
                st.markdown(type_badge)
                col_q1, col_q2 = st.columns([0.12, 0.88])
                with col_q1:
                    st.button(
                        f"▶️ {quote['time']}",
                        key=f"quote_{idx}",
                        on_click=set_audio_time,
                        args=(int(quote['start']),)
                    )
                with col_q2:
                    st.markdown(f"*{quote['text']}*")
                    if quote['full_context'] and quote['full_context'] != quote['text']:
                        with st.expander("📄 Ver contexto completo"):
                            st.markdown(quote['full_context'])
                st.markdown("---")
        else:
            st.info("💬 No se identificaron citas o declaraciones relevantes.")

    # ===== PESTAÑA 4: PERSONAS CLAVE =====
    if len(tabs) > 3:
        with tabs[3]:
            st.markdown("### 👥 Personas y Cargos Mencionados")
            people_data = st.session_state.get('people', [])
            
            if people_data and not any("Error" in str(person.get('name', '')) for person in people_data):
                st.caption(f"Se identificaron {len(people_data)} personas clave.")
                for person in people_data:
                    st.markdown(f"**👤 {person.get('name', 'Desconocido')}**")
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;*Rol:* {person.get('role', 'No especificado')}")
                    with st.expander("📝 Ver contexto"):
                        st.markdown(f"> {person.get('context', 'Sin contexto disponible.')}")
            elif people_data:
                st.error(f"**{people_data[0].get('name', 'Error')}**: {people_data[0].get('role', 'Error desconocido')}")
                st.info(f"Contexto del error: {people_data[0].get('context', 'No disponible')}")
            else:
                st.info("👤 No se identificaron personas o cargos específicos en el audio.")

    # Botón de limpiar
    st.markdown("---")
    if st.button("🗑️ Limpiar Todo y Empezar de Nuevo"):
        keys_to_delete = [
            "transcription", "transcription_data", "uploaded_audio_bytes",
            "audio_start_time", "summary", "quotes", "last_search",
            "search_counter", "people", "qa_history", "audio_player_key"
        ]
        for key in keys_to_delete:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

st.markdown("---")
st.markdown("""<div style='text-align: center; color: #666;'>
<p><strong>Transcriptor Pro - Johnascriptor - v2.5.0 (Corregido y Optimizado)</strong> - Desarrollado por Johnathan Cortés 🤖</p>
<p style='font-size: 0.85rem;'>✨ Con búsqueda contextual mejorada, Q&A interactivo, manejo robusto de errores y extracción de entidades en español</p>
</div>""", unsafe_allow_html=True)
        st.text_input("🔐 Contraseña", type="password", on_change=validate_password, key="password")
        
        if st.session_state.get("password_attempted", False) and not st.session_state.password_correct:
            st.error("❌ Contraseña incorrecta. Inténtalo de nuevo.")
    
    st.stop()

# --- INICIO DE LA APP PRINCIPAL ---

st.set_page_config(page_title="Transcriptor Pro - Johnascriptor", page_icon="🎙️", layout="wide")

# --- INICIALIZACIÓN DE ESTADO ---
if 'audio_start_time' not in st.session_state:
    st.session_state.audio_start_time = 0
if 'audio_player_key' not in st.session_state:
    st.session_state.audio_player_key = 0

# --- FUNCIÓN CALLBACK PARA CAMBIAR EL TIEMPO DEL AUDIO ---
def set_audio_time(start_seconds):
    st.session_state.audio_start_time = start_seconds
    st.session_state.audio_player_key += 1

# --- VALIDACIÓN DE API KEY ---
try:
    api_key = st.secrets["GROQ_API_KEY"]
    if not api_key or len(api_key) < 10:
        raise ValueError("API Key inválida")
except (KeyError, ValueError) as e:
    st.error("❌ Error: No se encontró GROQ_API_KEY válida en los secrets de Streamlit")
    st.info("Por favor configura tu API Key en Settings → Secrets")
    st.stop()

# --- DICCIONARIO COMPLETO DE CORRECCIONES ESPAÑOLAS (CORREGIDO) ---

SPANISH_WORD_CORRECTIONS = {
    # Corrección de "Sí" confundido con "S"
    r'\bS\s+([A-Z][a-zá-úñ]+)\b': r'Sí, \1',
    
    # Preguntas comunes
    r'\bqu\s+se\b': 'qué se',
    r'\bqu\s+es\b': 'qué es',
    r'\bqu\s+fue\b': 'qué fue',
    r'\bqu\s+hay\b': 'qué hay',
    r'\bqu\s+significa\b': 'qué significa',
    r'\bqu\s+pasa\b': 'qué pasa',
    r'\bPor\s+qu(?!\s+[eé])\b': 'Por qué',
    r'\bpor\s+qu(?!\s+[eé])\b': 'por qué',
    
    # Palabras comunes cortadas (CORREGIDO: todas con r' prefix)
    r'\bfundaci(?=\s|$)': 'fundación',
    r'\bFundaci(?=\s|$)': 'Fundación',
    r'\binformaci(?=\s|$)': 'información',
    r'\bInformaci(?=\s|$)': 'Información',
    r'\bsituaci(?=\s|$)': 'situación',
    r'\bSituaci(?=\s|$)': 'Situación',
    r'\bdeclaraci(?=\s|$)': 'declaración',
    r'\bDeclaraci(?=\s|$)': 'Declaración',
    r'\bnaci(?=\s|$)': 'nación',
    r'\bNaci(?=\s|$)': 'Nación',
    r'\bpoblaci(?=\s|$)': 'población',
    r'\bPoblaci(?=\s|$)': 'Población',
    r'\breuni(?=\s|$)': 'reunión',
    r'\bReuni(?=\s|$)': 'Reunión',
    r'\bopini(?=\s|$)': 'opinión',
    r'\bOpini(?=\s|$)': 'Opinión',
    r'\bresoluci(?=\s|$)': 'resolución',
    r'\bResoluci(?=\s|$)': 'Resolución',
    r'\borganizaci(?=\s|$)': 'organización',
    r'\bOrganizaci(?=\s|$)': 'Organización',
    r'\bprotecci(?=\s|$)': 'protección',
    r'\bProtecci(?=\s|$)': 'Protección',
    r'\bparticipaci(?=\s|$)': 'participación',
    r'\bParticipaci(?=\s|$)': 'Participación',
    r'\binvestigaci(?=\s|$)': 'investigación',
    r'\bInvestigaci(?=\s|$)': 'Investigación',
    r'\beducaci(?=\s|$)': 'educación',
    r'\bEducaci(?=\s|$)': 'Educación',
    r'\bsanci(?=\s|$)': 'sanción',
    r'\bSanci(?=\s|$)': 'Sanción',
    r'\bcomunicaci(?=\s|$)': 'comunicación',
    r'\bComunicaci(?=\s|$)': 'Comunicación',
    r'\boperaci(?=\s|$)': 'operación',
    r'\bOperaci(?=\s|$)': 'Operación',
    r'\brelaci(?=\s|$)': 'relación',
    r'\bRelaci(?=\s|$)': 'Relación',
    r'\badministraci(?=\s|$)': 'administración',
    r'\bAdministraci(?=\s|$)': 'Administración',
    r'\bimplementaci(?=\s|$)': 'implementación',
    r'\bImplementaci(?=\s|$)': 'Implementación',
    
    # Palabras terminadas en -ía
    r'\bpoli(?=\s|$)': 'política',
    r'\bPoli(?=\s|$)': 'Política',
    r'\bcompa(?=\s|$)': 'compañía',
    r'\bCompa(?=\s|$)': 'Compañía',
    r'\beconom(?=\s|$)': 'economía',
    r'\bEconom(?=\s|$)': 'Economía',
    r'\benergi(?=\s|$)': 'energía',
    r'\bEnergi(?=\s|$)': 'Energía',
    r'\bgeograf(?=\s|$)': 'geografía',
    r'\bGeograf(?=\s|$)': 'Geografía',
    
    # Otras palabras comunes
    r'\bpai(?=\s|$)': 'país',
    r'\bPai(?=\s|$)': 'País',
    r'\bda(?=\s|$)': 'día',
    r'\bDa(?=\s|$)': 'Día',
    r'\bmiérco(?=\s|$)': 'miércoles',
    r'\bMiérco(?=\s|$)': 'Miércoles',
    r'\bdocument(?=\s|$)': 'documental',
    r'\bDocument(?=\s|$)': 'Documental',
    r'\bsostenib(?=\s|$)': 'sostenible',
    r'\bSostenib(?=\s|$)': 'Sostenible',
    r'\bEntretenim(?=\s|$)': 'Entretenimiento',
    r'\bentretenim(?=\s|$)': 'entretenimiento',
}

# --- FUNCIONES AUXILIARES ORIGINALES ---

def create_copy_button(text_to_copy):
    text_json = json.dumps(text_to_copy)
    button_id = f"copy-button-{hash(text_to_copy)}"
    button_html = f"""
    <button id="{button_id}" style="width: 100%; padding: 0.25rem 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(49, 51, 63, 0.2); background-color: #FFFFFF; color: #31333F;">
        📋 Copiar Todo
    </button>
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
    </script>
    """
    components.html(button_html, height=40)

def format_timestamp(seconds):
    """Formatea segundos a formato HH:MM:SS"""
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds_val:02}"

def format_transcription_with_timestamps(data):
    """Formatea la transcripción con timestamps"""
    if not hasattr(data, 'segments') or not data.segments:
        return "No se encontraron segmentos con marcas de tiempo."
    lines = [
        f"[{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}] {seg['text'].strip()}"
        for seg in data.segments
    ]
    return "\n".join(lines)

# --- FUNCIÓN MEJORADA: POST-PROCESAMIENTO PARA TILDES Y PALABRAS CORTADAS ---

def fix_spanish_encoding(text):
    """Corrige problemas de encoding y palabras cortadas en español"""
    if not text:
        return text
    
    result = text
    
    try:
        # PASO 1: Corregir problemas de encoding UTF-8
        encoding_fixes = {
            'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
            'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡'
        }
        for wrong, correct in encoding_fixes.items():
            result = result.replace(wrong, correct)

        # PASO 2: Aplicar todas las correcciones del diccionario
        for pattern, replacement in SPANISH_WORD_CORRECTIONS.items():
            result = re.sub(pattern, replacement, result)

        # PASO 3: Limpieza de artefactos y duplicaciones comunes
        result = re.sub(r'([a-záéíóúñ])\1{2,}', r'\1', result, flags=re.IGNORECASE)
        
        # PASO 4: Corrección de mayúsculas al inicio de la frase después de un punto
        result = re.sub(r'(?<=\.\s)([a-z])', lambda m: m.group(1).upper(), result)

    except Exception as e:
        st.warning(f"⚠️ Error al corregir texto: {str(e)}")
        return text

    return result.strip()

def check_transcription_quality(text):
    """Verifica la calidad de la transcripción"""
    if not text:
        return []
    issues = []
    if any(char in text for char in ['Ã', 'Â']):
        issues.append("⚠️ Detectados problemas de encoding - Se aplicó corrección automática.")
    if re.search(r'\b(qu|sostenib|fundaci|informaci)\s', text, re.IGNORECASE):
        issues.append("ℹ️ Se aplicaron correcciones automáticas de tildes y palabras cortadas.")
    return issues

# --- FUNCIONES DE CONVERSIÓN Y COMPRESIÓN (MEJORADAS) ---

def convert_video_to_audio(video_bytes, video_filename):
    """Convierte video a audio con manejo robusto de errores"""
    video_path = None
    audio_path = None
    video = None
    
    try:
        # Crear archivo temporal de video
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video_filename)[1]) as tmp_video:
            tmp_video.write(video_bytes)
            video_path = tmp_video.name
        
        audio_path = video_path.rsplit('.', 1)[0] + '_audio.mp3'
        
        # Convertir a audio
        video = VideoFileClip(video_path)
        
        if video.audio is None:
            raise ValueError("El video no contiene pista de audio")
            
        video.audio.write_audiofile(
            audio_path, 
            codec='mp3', 
            bitrate='128k', 
            verbose=False, 
            logger=None
        )
        
        # Leer el archivo de audio generado
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        
        return audio_bytes, True
        
    except Exception as e:
        st.error(f"Error al convertir video: {str(e)}")
        return video_bytes, False
        
    finally:
        # Limpieza garantizada
        if video is not None:
            try:
                video.close()
            except:
                pass
        
        if video_path and os.path.exists(video_path):
            try:
                os.unlink(video_path)
            except:
                pass
                
        if audio_path and os.path.exists(audio_path):
            try:
                os.unlink(audio_path)
            except:
                pass

def compress_audio(audio_bytes, original_filename):
    """Comprime audio con manejo robusto de errores"""
    audio_path = None
    compressed_path = None
    audio = None
    
    try:
        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_audio:
            tmp_audio.write(audio_bytes)
            audio_path = tmp_audio.name
        
        compressed_path = audio_path.rsplit('.', 1)[0] + '_compressed.mp3'
        
        # Comprimir
        audio = AudioFileClip(audio_path)
        audio.write_audiofile(
            compressed_path, 
            codec='mp3', 
            bitrate='96k', 
            verbose=False, 
            logger=None
        )
        
        # Leer archivo comprimido
        with open(compressed_path, 'rb') as f:
            compressed_bytes = f.read()
        
        return compressed_bytes
        
    except Exception as e:
        st.warning(f"⚠️ No se pudo comprimir el audio: {str(e)}")
        return audio_bytes
        
    finally:
        # Limpieza garantizada
        if audio is not None:
            try:
                audio.close()
            except:
                pass
                
        if audio_path and os.path.exists(audio_path):
            try:
                os.unlink(audio_path)
            except:
                pass
                
        if compressed_path and os.path.exists(compressed_path):
            try:
                os.unlink(compressed_path)
            except:
                pass

def get_file_size_mb(file_bytes):
    """Calcula el tamaño del archivo en MB"""
    return len(file_bytes) / (1024 * 1024)

# --- FUNCIONES DE ANÁLISIS (MEJORADAS) ---

def generate_summary(transcription_text, client):
    """Genera un resumen del texto transcrito"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "Eres un asistente experto en análisis de noticias. Crea resúmenes profesionales y concisos en un solo párrafo. Mantén todas las tildes y acentos correctos en español."
                },
                {
                    "role": "user", 
                    "content": f"Escribe un resumen ejecutivo en un solo párrafo (máximo 150 palabras) del siguiente texto. Ve directo al contenido, sin introducciones. Mantén todas las tildes correctas:\n\n{transcription_text}"
                }
            ],
            model="llama-3.1-70b-versatile",
            temperature=0.3,
            max_tokens=500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al generar resumen: {str(e)}"

def answer_question(question, transcription_text, client, conversation_history):
    """Responde preguntas sobre la transcripción usando el contexto completo"""
    try:
        messages = [
            {
                "role": "system", 
                "content": """Eres un asistente experto en análisis de contenido. Responde preguntas sobre la transcripción proporcionada de manera precisa, concisa y profesional. 
                Reglas importantes:
                - Basa tus respuestas ÚNICAMENTE en la información de la transcripción
                - Si la información no está en la transcripción, indícalo claramente
                - Mantén todas las tildes y acentos correctos en español
                - Sé específico y cita partes relevantes cuando sea apropiado
                - Si te hacen una pregunta de seguimiento, considera el contexto de la conversación anterior"""
            }
        ]
        
        # Agregar historial de conversación
        for qa in conversation_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        
        # Agregar pregunta actual
        messages.append({
            "role": "user", 
            "content": f"""Transcripción completa del audio:
---
{transcription_text}
---
Pregunta: {question}
Responde basándote exclusivamente en la transcripción anterior."""
        })
        
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.1-70b-versatile",
            temperature=0.2,
            max_tokens=800
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error al procesar la pregunta: {str(e)}"

def extract_quotes(segments):
    """Extrae citas y declaraciones relevantes"""
    quotes = []
    quote_keywords = ['dijo', 'afirmó', 'declaró', 'señaló', 'expresó', 'manifestó', 'indicó', 'comentó', 'aseguró']
    
    for i, seg in enumerate(segments):
        text = seg['text'].strip()
        text_lower = text.lower()
        
        has_quotes = '"' in text or '«' in text or '»' in text
        has_declaration = any(keyword in text_lower for keyword in quote_keywords)
        
        if has_quotes or has_declaration:
            context_before = segments[i-1]['text'].strip() if i > 0 else ""
            context_after = segments[i+1]['text'].strip() if i < len(segments) - 1 else ""
            full_context = f"{context_before} {text} {context_after}".strip()
            
            quotes.append({
                'time': format_timestamp(seg['start']),
                'text': text,
                'full_context': full_context,
                'start': seg['start'],
                'type': 'quote' if has_quotes else 'declaration'
            })
    
    # Ordenar por tipo y longitud
    quotes.sort(key=lambda x: (x['type'] == 'quote', len(x['text'])), reverse=True)
    return quotes[:10]

def extract_people_and_roles(transcription_text, client):
    """Extrae personas y sus roles del texto (MEJORADO)"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": """Eres un analista experto en transcripciones de noticias. Tu tarea es identificar a todas las personas mencionadas por su nombre y, si se especifica, su cargo o rol.
                    
                    IMPORTANTE: Debes devolver ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
                    {
                        "people": [
                            {
                                "name": "Nombre Completo",
                                "role": "Cargo o Rol",
                                "context": "Frase donde se menciona"
                            }
                        ]
                    }
                    
                    Si no se menciona un rol, usa "No especificado".
                    Si no hay personas mencionadas, devuelve: {"people": []}
                    """
                },
                {
                    "role": "user",
                    "content": f"Analiza la siguiente transcripción y extrae las personas y sus roles:\n\n{transcription_text}"
                }
            ],
            model="llama-3.1-70b-versatile",
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"}
        )
        
        response_content = chat_completion.choices[0].message.content
        data = json.loads(response_content)
        
        # Buscar la lista de personas en diferentes estructuras posibles
        if "people" in data:
            return data["people"] if isinstance(data["people"], list) else []
        
        # Si no hay clave "people", buscar cualquier lista
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > 0:
                return data[key]
        
        return []

    except json.JSONDecodeError as e:
        st.error(f"Error al parsear JSON: {str(e)}")
        return [{
            "name": "Error de Análisis",
            "role": "No se pudo procesar la respuesta",
            "context": f"JSON inválido: {str(e)}"
        }]
    except Exception as e:
        st.error(f"Error en extracción de personas: {str(e)}")
        return [{
            "name": "Error de API",
            "role": str(e),
            "context": "Ocurrió un error al contactar con el servicio de análisis."
        }]

def get_extended_context(segments, match_index, context_range=2):
    """Obtiene el contexto extendido alrededor de un segmento"""
    start_idx = max(0, match_index - context_range)
    end_idx = min(len(segments), match_index + context_range + 1)
    
    context_segments = []
    for i in range(start_idx, end_idx):
        seg = segments[i]
        is_match = (i == match_index)
        context_segments.append({
            'text': seg['text'].strip(),
            'time': format_timestamp(seg['start']),
            'start': seg['start'],
            'is_match': is_match
        })
    return context_segments

def export_to_srt(data):
    """Exporta la transcripción a formato SRT"""
    srt_content = []
    for i, seg in enumerate(data.segments, 1):
        start_time = timedelta(seconds=seg['start'])
        end_time = timedelta(seconds=seg['end'])
        
        start = f"{start_time.seconds // 3600:02}:{(start_time.seconds // 60) % 60:02}:{start_time.seconds % 60:02},{start_time.microseconds // 1000:03}"
        end = f"{end_time.seconds // 3600:02}:{(end_time.seconds // 60) % 60:02}:{end_time.seconds % 60:02},{end_time.microseconds // 1000:03}"
        text = seg['text'].strip()
        
        srt_content.append(f"{i}\n{start} --> {end}\n{text}\n")
    
    return "\n".join(srt_content)

# --- INTERFAZ DE LA APP ---

st.title("🎙️ Transcriptor Pro - Johnascriptor")

with st.sidebar:
    st.header("⚙️ Configuración")
    model_option = st.selectbox(
        "Modelo de Transcripción",
        ["whisper-large-v3"],
        index=0,
        help="Large-v3: Máxima precisión para español (RECOMENDADO)"
    )
    language = st.selectbox(
        "Idioma",
        ["es"],
        index=0,
        help="Español seleccionado por defecto para máxima calidad de corrección."
    )
    temperature = st.slider(
        "Temperatura",
        0.0, 1.0, 0.0, 0.1,
        help="Mantén en 0.0 para máxima precisión"
    )
    
    st.markdown("---")
    st.subheader("🎯 Análisis Inteligente")
    enable_tilde_fix = st.checkbox(
        "✨ Corrección automática de tildes",
        value=True,
        help="Repara palabras cortadas y corrige acentos (altamente recomendado)."
    )
    enable_summary = st.checkbox("📝 Generar resumen automático", value=True)
    enable_quotes = st.checkbox("💬 Identificar citas y declaraciones", value=True)
    enable_people = st.checkbox("👤 Extraer personas y cargos", value=True)
    
    st.markdown("---")
    st.subheader("🔍 Búsqueda Contextual")
    context_lines = st.slider(
        "Líneas de contexto",
        1, 5, 2,
        help="Número de líneas antes y después del resultado"
    )

    st.markdown("---")
    st.subheader("🔧 Procesamiento de Audio")
    if MOVIEPY_AVAILABLE:
        st.info("💡 Los archivos MP4 > 25 MB se convertirán a audio automáticamente.")
        compress_audio_option = st.checkbox("📦 Comprimir audio (reduce tamaño)", value=False)
    else:
        st.warning("⚠️ MoviePy no disponible para conversión de video.")
        compress_audio_option = False
    
    st.markdown("---")
    st.info("💡 **Formatos:** MP3, MP4, WAV, WEBM, M4A, MPEG, MPGA")
    st.success("✅ API Key configurada correctamente")

st.subheader("📤 Sube tu archivo de audio o video")
col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader(
        "Selecciona un archivo",
        type=["mp3", "mp4", "wav", "webm", "m4a", "mpeg", "mpga"],
        label_visibility="collapsed"
    )
with col2:
