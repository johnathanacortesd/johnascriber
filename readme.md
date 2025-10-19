# 🎙️ Transcriptor Pro Johnascriptor: Análisis Avanzado de Audio con Groq y Streamlit

![alt text](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)

![Transcriptor Pro JC](https://github.com/user-attachments/assets/edd8e396-8efa-40ec-8ab2-ce289168c597)

Transcriptor Pro Johnascriptor es una herramienta web que va más allá de la simple transcripción. Usa la velocidad de la API de Groq y la potencia de modelos de IA de última generación para convertir archivos de audio y video en texto, y luego generar análisis inteligentes como resúmenes ejecutivos y extracción de citas clave. Diseñada para analistas que necesitan resultados rápidos, precisos y procesables.

---

## ✨ Características Principales

### Análisis con Inteligencia Artificial

* 🎯 **Alta Precisión**: Usa `whisper-large-v3` de OpenAI para garantizar una de las transcripciones más precisas del mercado.
* 📝 **Resumen Ejecutivo Automático**: Usa el modelo `llama-3.3-70b-versatile` para generar resúmenes concisos y profesionales del contenido transcrito.
* 💬 **Extracción de Citas y Declaraciones**: Identifica y aísla automáticamente las citas textuales más importantes, mostrando quién dijo qué y en qué momento.
* ▶️ **Reproducción Interactiva**: Cada cita incluye un botón para saltar directamente al momento correspondiente en el reproductor de audio.

### Transcripción y Usabilidad

* ⚡ **Velocidad Extrema**: Gracias a la infraestructura de Groq, las transcripciones se completan en segundos.
* 🎬 **Soporte para Audio y Video**: Acepta archivos `.mp3`, `.wav`, `.m4a`, `.mp4`, `.webm`, `.mpeg`.
* 📦 **Compresión Automática Inteligente**: Archivos de video mayores a 25 MB se convierten a MP3 automáticamente.
* 🔎 **Búsqueda Contextual**: Permite buscar palabras clave y verlas dentro de su contexto.
* 🎨 **Diseño Mejorado para Lectura**: Texto oscuro, tipografía monoespaciada y resaltado de alta visibilidad.
* 🔒 **Acceso Seguro con Contraseña**: Protege la aplicación con una contraseña única.

### Exportación y Productividad

* 📥 **Múltiples Opciones de Descarga**:

  * Texto Plano (`.txt`)
  * Texto con Marcas de Tiempo (`.txt`)
  * Subtítulos (`.srt`)
* 📋 **Copia Rápida**: Botones para copiar la transcripción o el resumen al portapapeles.

---

## ⚙️ Cómo Funciona

1. **Autenticación**: El usuario introduce una contraseña.
2. **Carga**: Se sube un archivo de audio o video (se comprime si es grande).
3. **Transcripción**: Groq procesa el audio con Whisper y devuelve el texto.
4. **Análisis**: Llama 3.3 genera el resumen y se extraen citas clave.
5. **Visualización Interactiva**: Se muestran transcripción, resumen y citas con herramientas de búsqueda.

---

## ⚠️ Restricciones y Limitaciones

### 1. Límites de la API Gratuita de Groq

* Duración diaria: 28 800 s (8 h de audio).
* Tamaño máximo por archivo: 25 MB.
* Límite de peticiones: 30 RPM, 1 000 – 14 400 RPD según el modelo.

### 2. Limitaciones de la Aplicación

* Contraseña global (no hay cuentas individuales).
* No guarda transcripciones (sin persistencia).

---

## 🧩 Dependencias Principales

* `groq`
* `moviepy`
* `whisper-large-v3`

Documentación oficial de Groq: [https://console.groq.com/docs/model/whisper-large-v3](https://console.groq.com/docs/model/whisper-large-v3)
