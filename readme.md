# 🎙️ Transcriptor de Audio con Groq y Streamlit

[![Abrir en Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://johnascriber.streamlit.app/)

![johanscriber](https://github.com/user-attachments/assets/e368cdc8-4fac-4081-9373-76174ae48840)


## ✨ Ventajas y Características Principales

Este proyecto fue diseñado para ser una herramienta de transcripción rápida, privada y eficiente.

*   **⚡ Velocidad Extrema**: Gracias a la infraestructura de Groq, las transcripciones de audios de varios minutos se completan en cuestión de segundos, no minutos.
*   **🎯 Alta Precisión**: Utiliza el modelo `whisper-large-v3` de OpenAI, uno de los modelos de reconocimiento de voz más avanzados disponibles.
*   **🔒 Acceso Seguro con Contraseña**: Para mayor seguridad, **el acceso a la aplicación está protegido por una contraseña única**. Esto asegura que solo los usuarios autorizados puedan utilizar la herramienta de transcripción.
*   **🌐 Soporte Multilingüe**: Permite seleccionar el idioma del audio de una lista predefinida para mejorar la precisión de la transcripción.
*   **🔎 Búsqueda Inteligente**: Incluye una función de búsqueda que resalta todas las coincidencias de una palabra clave directamente en la transcripción, mostrando el momento exacto (`[HH:MM:SS]`) en que fue dicha.
*   **📥 Múltiples Opciones de Descarga**:
    1.  **Texto Plano (.txt)**: Descarga la transcripción completa y limpia.
    2.  **Texto con Marcas de Tiempo (.txt)**: Descarga la transcripción segmentada con marcas de tiempo `[HH:MM:SS --> HH:MM:SS]`, ideal para subtítulos o análisis.
*   **📋 Funcionalidades Útiles**: Incluye un botón para copiar todo el texto al portapapeles con un solo clic.
*   **🚀 Fácil de Desplegar**: Listo para ser desplegado en plataformas como Streamlit Community Cloud con una configuración mínima.

---
(El resto del README.md sigue igual)
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

## 🚀 Instalación y Despliegue

### Despliegue en Streamlit Community Cloud (Recomendado)

1.  **Haz un Fork** de este repositorio en tu cuenta de GitHub.
2.  **Ve a [Streamlit Community Cloud](https://share.streamlit.io/)** y haz clic en "New app".
3.  **Conecta tu repositorio** y selecciona el archivo principal de la aplicación (ej: `app.py`).
4.  **Configura los Secretos**: En la configuración avanzada (`Advanced settings...`), añade tus secretos:
    ```toml
    GROQ_API_KEY = "gsk_TU_API_KEY_DE_GROQ"
    PASSWORD = "la_contraseña_secreta_que_quieras"
    ```
5.  **Despliega**: Haz clic en "Deploy!" y espera a que tu aplicación esté en línea.

### Ejecución Local

Para ejecutar esta aplicación en tu propia máquina, sigue estos pasos:

**1. Clona el Repository**
```bash
git clone https://github.com/tu-usuario/tu-repositorio.git
cd tu-repositorio
