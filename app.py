import streamlit as st
import os
import tempfile
from groq import Groq
import re
from datetime import timedelta
import json

# ============================================
# CONFIGURACIÓN
# ============================================
st.set_page_config(
    page_title="Transcripción Precisa de Audio",
    page_icon="🎙️",
    layout="wide"
)

# Inicializar cliente Groq
try:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
except:
    st.error("❌ Error: GROQ_API_KEY no encontrada en secrets")
    st.stop()

# ============================================
# UTILIDADES
# ============================================

def formato_timestamp(segundos: float) -> str:
    """Convierte segundos a formato [HH:MM:SS]"""
    td = timedelta(seconds=int(segundos))
    horas = td.seconds // 3600
    minutos = (td.seconds % 3600) // 60
    segs = td.seconds % 60
    return f"[{horas:02d}:{minutos:02d}:{segs:02d}]"

def limpiar_texto_basico(texto: str) -> str:
    """Limpieza básica sin LLM para preservar fidelidad"""
    if not texto:
        return ""
    
    # Normalizar espacios
    texto = re.sub(r'\s+', ' ', texto)
    
    # Eliminar artefactos comunes de Whisper
    texto = re.sub(r'\[música\]|\[Music\]|\[MÚSICA\]', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\[aplausos\]|\[Applause\]', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\[risas\]|\[Laughter\]', '', texto, flags=re.IGNORECASE)
    
    # Corregir puntuación
    texto = re.sub(r'\s+([.,;:!?])', r'\1', texto)
    texto = re.sub(r'([.,;:!?])([A-ZÁÉÍÓÚÑ])', r'\1 \2', texto)
    
    return texto.strip()

def limpiar_con_llm(texto: str, usar_llm: bool = True, modelo: str = "llama") -> str:
    """
    Limpieza avanzada con LLM (opcional)
    Modelos soportados: 'llama' (Groq), 'gpt' (OpenAI), 'claude' (Anthropic)
    """
    if not usar_llm or not texto:
        return limpiar_texto_basico(texto)
    
    prompt = f"""Eres un editor de texto experto en español. Limpia esta transcripción:

REGLAS ESTRICTAS:
- NO inventes contenido nuevo
- NO resumas ni parafrasees
- SOLO corrige errores ortográficos y puntuación
- Mantén TODAS las palabras originales
- Preserva nombres propios exactamente
- Asegura tildes correctas en español

TEXTO:
{texto}

Responde SOLO con el texto corregido, sin explicaciones."""
    
    try:
        # OPCIÓN 1: Llama 3.3 70B via Groq (usa la misma API key que Whisper)
        if modelo == "llama":
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # ← MODELO MEJORADO
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un editor de texto preciso. Solo corriges errores sin cambiar contenido."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=4000,
                top_p=1
            )
            texto_limpio = completion.choices[0].message.content.strip()
            return texto_limpio
        
        # OPCIÓN 2: GPT-4o-mini (requiere OPENAI_API_KEY)
        elif modelo == "gpt":
            import openai
            openai.api_key = st.secrets.get("OPENAI_API_KEY")
            
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000
            )
            texto_limpio = response.choices[0].message.content.strip()
            return texto_limpio
        
        # OPCIÓN 3: Claude 3.5 Haiku (requiere ANTHROPIC_API_KEY)
        elif modelo == "claude":
            import anthropic
            client_claude = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            
            message = client_claude.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=4000,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            texto_limpio = message.content[0].text.strip()
            return texto_limpio
        
        else:
            return limpiar_texto_basico(texto)
        
    except Exception as e:
        st.warning(f"⚠️ Limpieza con LLM falló, usando limpieza básica: {e}")
        return limpiar_texto_basico(texto)

def transcribir_audio_mejorado(audio_path: str, idioma: str = "es") -> dict:
    """
    Transcripción optimizada para español con timestamps precisos
    """
    try:
        with open(audio_path, "rb") as audio_file:
            # Configuración optimizada para español
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), audio_file.read()),
                model="whisper-large-v3",  # Mejor modelo disponible
                language=idioma,  # Forzar idioma español
                response_format="verbose_json",  # Incluye timestamps detallados
                temperature=0.0,  # Máxima determinismo
                prompt="Transcripción en español con tildes y puntuación correcta."
            )
        
        return {
            "text": transcription.text,
            "segments": transcription.segments if hasattr(transcription, 'segments') else [],
            "language": transcription.language
        }
    
    except Exception as e:
        st.error(f"❌ Error en transcripción: {e}")
        return None

def buscar_en_transcripcion(texto_completo: str, segments: list, query: str) -> list:
    """
    Búsqueda mejorada con contexto y timestamps precisos
    """
    if not query.strip():
        return []
    
    query_lower = query.lower()
    resultados = []
    
    # Búsqueda en segmentos con timestamp
    for seg in segments:
        texto_seg = seg.get('text', '').lower()
        
        if query_lower in texto_seg:
            # Contexto: segmento anterior y siguiente
            contexto = seg.get('text', '')
            
            resultados.append({
                'timestamp': seg.get('start', 0),
                'timestamp_fmt': formato_timestamp(seg.get('start', 0)),
                'texto': contexto.strip(),
                'inicio': seg.get('start', 0),
                'fin': seg.get('end', 0)
            })
    
    return resultados

# ============================================
# INTERFAZ
# ============================================

st.title("🎙️ Transcripción Precisa de Audio")
st.markdown("### Optimizado para español con búsqueda temporal")

# Sidebar con configuración
with st.sidebar:
    st.header("⚙️ Configuración")
    
    usar_limpieza_llm = st.checkbox(
        "Usar limpieza avanzada con IA",
        value=False,
        help="Requiere OPENAI_API_KEY. Mejora ortografía sin alterar contenido."
    )
    
    idioma = st.selectbox(
        "Idioma del audio",
        options=["es", "en", "fr", "de", "it", "pt"],
        index=0,
        format_func=lambda x: {
            "es": "🇪🇸 Español",
            "en": "🇺🇸 Inglés", 
            "fr": "🇫🇷 Francés",
            "de": "🇩🇪 Alemán",
            "it": "🇮🇹 Italiano",
            "pt": "🇧🇷 Portugués"
        }[x]
    )
    
    st.markdown("---")
    st.info("""
    **💡 Consejos:**
    - Audios claros = mejor precisión
    - Máximo 25MB por archivo
    - Formatos: MP3, WAV, M4A, MP4
    """)

# Uploader de archivo
audio_file = st.file_uploader(
    "📂 Sube tu archivo de audio",
    type=["mp3", "wav", "m4a", "mp4", "flac"],
    help="Tamaño máximo: 25MB"
)

if audio_file:
    st.audio(audio_file)
    
    if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True):
        
        # Guardar archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.name)[1]) as tmp_file:
            tmp_file.write(audio_file.read())
            tmp_path = tmp_file.name
        
        try:
            # Transcripción
            with st.status("🎯 Transcribiendo audio...", expanded=True) as status:
                st.write("Procesando con Whisper large-v3...")
                resultado = transcribir_audio_mejorado(tmp_path, idioma)
                
                if not resultado:
                    st.error("❌ Falló la transcripción")
                    st.stop()
                
                texto_original = resultado['text']
                segments = resultado.get('segments', [])
                
                st.write("✅ Transcripción completada")
                
                # Limpieza opcional
                if usar_limpieza_llm:
                    st.write("🧹 Limpiando texto con IA...")
                    texto_limpio = limpiar_con_llm(texto_original, True)
                else:
                    st.write("🧹 Limpieza básica...")
                    texto_limpio = limpiar_texto_basico(texto_original)
                
                status.update(label="✅ Proceso completado", state="complete")
            
            # Guardar en session_state
            st.session_state.update({
                'texto_original': texto_original,
                'texto_limpio': texto_limpio,
                'segments': segments,
                'idioma_detectado': resultado.get('language', idioma)
            })
            
        finally:
            # Limpiar archivo temporal
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

# ============================================
# RESULTADOS
# ============================================

if 'texto_limpio' in st.session_state:
    
    st.success("🎉 Transcripción disponible")
    
    # Tabs para organizar información
    tab1, tab2, tab3 = st.tabs(["📝 Transcripción", "🔍 Búsqueda", "📊 Detalles"])
    
    with tab1:
        st.subheader("Texto Transcrito")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            # Mostrar texto limpio por defecto
            st.text_area(
                "Transcripción limpia:",
                st.session_state.texto_limpio,
                height=400,
                key="texto_display"
            )
        
        with col2:
            st.metric("Idioma", st.session_state.get('idioma_detectado', 'N/A').upper())
            st.metric("Palabras", len(st.session_state.texto_limpio.split()))
            st.metric("Caracteres", len(st.session_state.texto_limpio))
            
            # Toggle para ver original
            if st.checkbox("Ver texto original"):
                st.text_area(
                    "Transcripción original:",
                    st.session_state.texto_original,
                    height=200
                )
        
        # Descargas
        st.download_button(
            "📥 Descargar TXT",
            st.session_state.texto_limpio,
            file_name=f"transcripcion_{audio_file.name}.txt",
            mime="text/plain",
            use_container_width=True
        )
    
    with tab2:
        st.subheader("Búsqueda Temporal")
        
        query = st.text_input(
            "🔎 Buscar palabra o frase:",
            placeholder="Ej: presupuesto, reunión, proyecto..."
        )
        
        if query:
            resultados = buscar_en_transcripcion(
                st.session_state.texto_limpio,
                st.session_state.segments,
                query
            )
            
            if resultados:
                st.success(f"✅ {len(resultados)} coincidencia(s) encontrada(s)")
                
                for i, res in enumerate(resultados, 1):
                    with st.expander(f"🎯 Resultado {i} - {res['timestamp_fmt']}"):
                        st.markdown(f"**Timestamp:** `{res['timestamp_fmt']}`")
                        st.markdown(f"**Contexto:**")
                        st.info(res['texto'])
                        st.caption(f"Duración: {res['inicio']:.1f}s - {res['fin']:.1f}s")
            else:
                st.warning("⚠️ No se encontraron coincidencias")
    
    with tab3:
        st.subheader("Información Detallada")
        
        if st.session_state.segments:
            st.write(f"**Segmentos totales:** {len(st.session_state.segments)}")
            
            # Mostrar primeros 10 segmentos con timestamps
            with st.expander("Ver primeros 10 segmentos"):
                for seg in st.session_state.segments[:10]:
                    col1, col2 = st.columns([1, 4])
                    col1.code(formato_timestamp(seg.get('start', 0)))
                    col2.write(seg.get('text', ''))
            
            # Exportar JSON completo
            if st.button("📥 Exportar JSON con timestamps"):
                json_data = json.dumps({
                    'texto_limpio': st.session_state.texto_limpio,
                    'texto_original': st.session_state.texto_original,
                    'segments': st.session_state.segments,
                    'idioma': st.session_state.idioma_detectado
                }, ensure_ascii=False, indent=2)
                
                st.download_button(
                    "Descargar JSON",
                    json_data,
                    file_name=f"transcripcion_completa_{audio_file.name}.json",
                    mime="application/json"
                )
        else:
            st.info("No hay segmentos con timestamps disponibles")

# Footer
st.markdown("---")
st.caption("🤖 Transcripción con Whisper large-v3 | Optimizado para español")
