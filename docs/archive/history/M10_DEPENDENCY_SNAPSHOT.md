# ARCHEON M10 — dependency snapshot

Fecha: 2026-08-28.

## CORE

- Python 3.12; paquete `archeon==10.0.0.dev0`.
- Biblioteca estándar para servidor local, red, persistencia y Core.
- `yt-dlp==2026.8.19`: resolver multimedia integrado y bajo demanda; no autoriza extracción oculta de YouTube.
- WebView2 es un runtime de Windows usado por `pywebview==6.2.1`; no se duplica Chromium dentro del paquete.

## OPTIONAL / LAZY RUNTIME

- Voz: `sounddevice 0.5.6`, `vosk 0.3.45`, `webrtcvad-wheels 2.0.14`, `comtypes 1.4.16`.
- Media: `miniaudio 1.71`, `Pillow 12.3.0`, `tinytag 2.3.0`.
- Documentos: `openpyxl 3.1.5`, `pypdf 6.10.0`, `python-docx 1.2.0`, `python-pptx 1.0.2`, `lxml 6.1.2`.
- IA local: llama.cpp administrado fuera del repositorio; Qwen3 GGUF en `%LOCALAPPDATA%\ARCHEON\models`.
- Visión: llama.cpp + modelo/proyector administrados y descargados de RAM al terminar.
- Imagen: stable-diffusion.cpp CPU/Vulkan y Real-ESRGAN NCNN Vulkan, separados del Core.
- FFmpeg: decoder opcional legítimo. La build completa del sistema solo se usó como referencia de desarrollo, no se empaquetó ni queda residente.
- Supabase: REST/Auth/PostgREST mediante HTTPS y clave publicable; no se empaqueta SDK pesado ni `service_role`.

## DEV / TEST

- `pytest 9.1.1`, `psutil 7.2.2`, `PyInstaller 6.16.0`, hooks 2026.6.
- Herramientas Office de validación y scripts de benchmark permanecen fuera del runtime instalado.
- La venv incluye además `requests`, `urllib3`, `websockets`, `pythonnet`, `xlsxwriter` y dependencias transitivas.

## EXTERNAL SERVICES

- Supabase Auth/Database/Settings Sync.
- Proveedor de correo y dominio verificado: no configurados completamente.
- Brave Search y YouTube Data API: opcionales por credencial; RSS oficial es fallback para noticias.
- YouTube: reproductor oficial visible para reproducción; no es decoder ni audio oculto.
- Resolvers/streams directos solo se aceptan para fuentes autorizadas.

## LEGACY / REMOVE CANDIDATE

- `archeon_updater.py`: updater antiguo sin contrato de release firmado.
- `archeon_cloud.py`, `archeon_music.py` y otros módulos raíz: referencia histórica, no owner del runtime actual.
- Firebase Admin y credenciales legacy: excluidos del paquete; revocar y retirar durante Consolidation.
- `ffmpeg-8.0.1-essentials_build`: no requerido por el paquete M10.
- Una venv duplicada, builds/dist M1–M9, runtime/temp repetidos y exportadores con rutas de usuario.

## PACKAGE RESULT

`dist-m10-final/Archeo32n` contiene 1,263 archivos / 117.30 MiB y cero GGUF, cero binarios FFmpeg y cero archivos con nombre de secreto/credencial. Los modelos y runtimes grandes permanecen fuera del núcleo y se cargan bajo demanda.
