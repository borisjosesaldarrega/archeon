# ARCHEON

ARCHEON es un asistente modular para Windows con procesamiento local, interfaz de escritorio, ARCHI, voz, multimedia, automatización controlada del equipo, documentos, creación de artefactos, programación, extensiones, autenticación y sincronización opcional.

Este repositorio es un respaldo privado del código fuente. No contiene claves, archivos `.env`, credenciales Firebase, modelos descargados, datos del usuario, builds ni entornos virtuales.

## Arquitectura

El único runtime activo vive en `src/archeon/`:

| Módulo | Responsabilidad |
|---|---|
| `app.py` | Composition root, routing general y coordinación de capacidades. |
| `core/` | Configuración, eventos, ciclo de vida, permisos, herramientas, mensajes y rutas seguras. |
| `agent/` | Planificación y ejecución de tareas, cancelación, contexto y evidencia. |
| `intelligence/` | Selección de modelos y proveedores de inteligencia. |
| `understanding/` | Reparación lingüística, negaciones y protección contra falsos positivos. |
| `voice/`, `audio/` | Wake Word, STT, TTS, WASAPI y verificación de voces autorizadas. |
| `media/` | Música, búsqueda, matching, metadata, reproducción, dispositivos y codecs opcionales. |
| `desktop/`, `vision/` | Observación de pantalla, cursor, clics, overlays y Computer Use. |
| `browser/`, `launcher/` | Navegación controlada y apertura de aplicaciones. |
| `context/` | Adjuntos, selección de archivos, presupuesto de contexto y continuidad de temas. |
| `documents/` | Lectura, edición, resolución, renderizado y validación de documentos. |
| `artifacts/` | Word, PDF, PowerPoint, hojas, imágenes, infografías, web y archivos comprimidos. |
| `programming/` | Detección de proyectos, planificación, edición y validación de código. |
| `plugins/` | Extensiones fail-closed, permisos, integridad y firma Ed25519. |
| `auth/` | Sesiones locales, Supabase Auth, OTP, recovery, MFA y protección DPAPI. |
| `sync/`, `cloud/` | Sincronización de preferencias y contratos de capacidades remotas. |
| `updates/` | Actualizaciones firmadas; permanece `NOT CONFIGURED` sin proveedor real. |
| `ui/` | Interfaz, Ghost, radial, accesibilidad y catálogos multilingües. |
| `system/`, `database/`, `learning/`, `search/` | Infraestructura compartida y proveedores auxiliares. |

La arquitectura detallada está en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) y [`docs/FINAL_ARCHITECTURE.md`](docs/FINAL_ARCHITECTURE.md).

## Dependencias e imports principales

El proyecto requiere Python 3.11 o posterior. Las dependencias declaradas están en `pyproject.toml`:

- `cryptography`: firmas Ed25519 y operaciones criptográficas.
- `yt-dlp`: resolver multimedia opcional y cargado bajo demanda.
- `pywebview`: ventana de escritorio.
- `psutil`: benchmarks y validación de procesos.
- `sounddevice`, `vosk`, `webrtcvad-wheels`, `comtypes`: captura, reconocimiento, VAD, TTS y APIs de Windows.
- `miniaudio`, `Pillow`, `tinytag`: reproducción, imágenes y metadata multimedia.
- `openpyxl`, `pypdf`, `python-docx`, `python-pptx`: creación, lectura y validación de artefactos.

Los módulos estándar más utilizados incluyen `pathlib`, `dataclasses`, `threading`, `subprocess`, `sqlite3`, `urllib`, `json`, `hashlib`, `secrets`, `ctypes` y `http.server`.

## Preparación del entorno

```powershell
py -3.12 -m venv .venv-archeon
.venv-archeon\Scripts\python.exe -m pip install -e ".[desktop,benchmark,voice,media,documents]"
```

Los modelos de voz no se guardan en Git. Deben restaurarse en el directorio de modelos configurado por ARCHEON.

## Ejecutar

```powershell
.venv-archeon\Scripts\python.exe -m archeon
```

Modo de diagnóstico sin ventana:

```powershell
.venv-archeon\Scripts\python.exe -m archeon --headless --auto-exit 2
```

## Pruebas

```powershell
.venv-archeon\Scripts\python.exe -m pytest -q
```

El último cierre local obtuvo 389 pruebas y 128 subpruebas aprobadas. Los flujos remotos de Supabase y correo necesitan infraestructura y cuentas controladas antes de poder declararse E2E.

## Build

La build de Windows usa `build_archeo.spec` y toma el entry point exclusivamente desde `src/archeon/__main__.py`:

```powershell
.venv-archeon\Scripts\python.exe -m PyInstaller --noconfirm --clean `
  --distpath dist-release-candidate `
  --workpath build-release-candidate `
  build_archeo.spec
```

Consulta [`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md), [`docs/SECURITY.md`](docs/SECURITY.md) y [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) antes de publicar una versión.

## Seguridad del respaldo

- Nunca subir `.env`, `.env.local`, `firebase_key*.json`, claves privadas ni tokens.
- No versionar `models/`, `backups/`, `output/`, `.recovery/`, builds o venvs.
- Los plugins de terceros no confiables requieren aislamiento AppContainer/broker antes de aceptarse.
- Las actualizaciones no deben habilitarse sin hash, firma y backend real.
- `USER VERIFIED` continúa en `false` hasta completar las pruebas privadas manuales.
