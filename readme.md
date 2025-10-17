# 🎙️ Transcriptor de Audio con Groq y Streamlit

Una aplicación web simple y potente para transcribir archivos de audio y video en segundos. Construida con [Streamlit](https://streamlit.io/) y potenciada por la increíble velocidad de la API de [Groq](https://groq.com/) que utiliza el modelo `whisper-large-v3` de OpenAI.

[![Abrir en Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://[johnapp-ghvnsz7rafze4s5ib59qsk.streamlit.app](https://johnascriber.streamlit.app/)


![Demo de la App](https://i.imgur.com/your-demo-image.gif)
*(Recomendación: Graba un GIF corto mostrando la app en acción y reemplaza la URL de arriba)*

---

## ✨ Ventajas y Características Principales

Este proyecto fue diseñado para ser una herramienta de transcripción rápida, privada y eficiente.

*   **⚡ Velocidad Extrema**: Gracias a la infraestructura de Groq, las transcripciones de audios de varios minutos se completan en cuestión de segundos, no minutos.
*   **🎯 Alta Precisión**: Utiliza el modelo `whisper-large-v3` de OpenAI, uno de los modelos de reconocimiento de voz más avanzados disponibles.
*   **🔒 Privacidad Asegurada**: Protegida por una contraseña única que se gestiona a través de los secretos de Streamlit, asegurando que solo usuarios autorizados puedan acceder.
*   **🌐 Soporte Multilingüe**: Permite seleccionar el idioma del audio de una lista predefinida para mejorar la precisión de la transcripción.
*   **🔎 Búsqueda Inteligente**: Incluye una función de búsqueda que resalta todas las coincidencias de una palabra clave directamente en la transcripción, mostrando el momento exacto (`[HH:MM:SS]`) en que fue dicha.
*   **📥 Múltiples Opciones de Descarga**:
    1.  **Texto Plano (.txt)**: Descarga la transcripción completa y limpia.
    2.  **Texto con Marcas de Tiempo (.txt)**: Descarga la transcripción segmentada con marcas de tiempo `[HH:MM:SS --> HH:MM:SS]`, ideal para subtítulos o análisis.
*   **📋 Funcionalidades Útiles**: Incluye un botón para copiar todo el texto al portapapeles con un solo clic.
*   **🚀 Fácil de Desplegar**: Listo para ser desplegado en plataformas como Streamlit Community Cloud con una configuración mínima.

---

## ⚙️ Cómo Funciona

La aplicación sigue un flujo sencillo:
1.  **Autenticación**: El usuario debe introducir una contraseña para acceder a la app.
2.  **Carga**: El usuario sube un archivo de audio o video a través de la interfaz de Streamlit.
3.  **Procesamiento**: El backend de Streamlit envía el archivo a la API de Groq.
4.  **Transcripción**: Groq procesa el audio con el modelo Whisper y devuelve el texto transcrito junto con datos detallados (como segmentos y tiempos) en formato `verbose_json`.
5.  **Visualización**: La aplicación muestra la transcripción completa, ofrece herramientas de búsqueda y permite la descarga de los resultados.

---

## ⚠️ Restricciones y Limitaciones

Este proyecto está sujeto a ciertas limitaciones, principalmente derivadas del uso de la capa gratuita de la API de Groq y de la naturaleza de la aplicación.

#### 1. Límites de la API Gratuita de Groq
El nivel gratuito es muy generoso, pero tiene límites que debes conocer:
*   **Límite de Duración Diario (el más importante)**: Puedes transcribir un máximo de **28,800 segundos** de audio por día.
    *   Esto equivale a **480 minutos** u **8 horas** de audio cada 24 horas.
*   **Tamaño Máximo de Archivo**: Cada archivo subido no puede exceder los **25 MB**.
    *   Para un MP3 a 128 kbps, esto representa aproximadamente 25-30 minutos.
    *   Para un archivo WAV sin comprimir, serán solo unos pocos minutos.
*   **Límites de Peticiones**: 20 peticiones por minuto y 2,000 por día. Es muy poco probable que alcances estos límites antes que el límite de duración.

#### 2. Limitaciones de la Aplicación
*   **Contraseña Global**: La aplicación utiliza una única contraseña para todos los usuarios. No es un sistema de cuentas individuales.
*   **Sin Persistencia de Datos**: La aplicación es "sin estado" (stateless). Las transcripciones no se guardan en ningún servidor o base de datos. Si cierras o refrescas la página, los resultados se perderán.

---
