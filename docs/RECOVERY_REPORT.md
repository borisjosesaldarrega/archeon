# ARCHEON Recovery Report

Date: 2026-08-21  
Scope: read-only/static recovery of the supplied source ZIP, the loose workspace, the v9.6 PyInstaller executable, and the v9.8 Inno Setup installer. Original supplied files were not overwritten or deleted.

## Executive summary

The recoverable project is a Python 3.10 desktop assistant built around a single large process: Flask serves an HTML/CSS/JavaScript UI, pywebview opens it, and eager imports initialize Firebase, speech recognition, TTS, music, prediction, system-control and AI modules. It is functional prototype code, but it is not a production-safe or resource-efficient architecture yet.

The strongest assets to preserve are the visual identity, the circular core/orb, the music-to-album-art transition, the local intent/rule prototypes, the context-memory concepts, and several working system/music primitives. The current startup model, secret handling, permission model, networking exposure, packaging and background polling must be replaced or substantially refactored.

The v9.8 installer is the newest supplied binary by declared product version and timestamp. It is an unsigned Inno Setup 6.6.1 package. Static extraction was attempted with current 7-Zip 26.02 and innoextract 1.12-dev (format support through Inno Setup 6.7.0); both rejected the archive. The installer was not executed. Exact v9.8 inner-code comparison is therefore `BLOCKED`, while its metadata and hash are preserved below.

## Supplied evidence and integrity

| Artifact | Size | SHA-256 | Result |
|---|---:|---|---|
| `asistente.zip` | 1,191,846,771 B | `86B1A3F847993724F5B6A225759481C6007B2A39E5063B1A44FF7EB5750ED015` | Primary immutable backup; 21,111 entries; 1,837,962,709 B uncompressed |
| `dist/Archeo32n.exe` | 267,476,692 B | `FA69C867ED220CC976D7C626953AFD1E51818D70D6DB95A1B9BADFDB7A23D136` | PyInstaller one-file v9.6-era application; statically listable |
| `web/Instalar_Archeon_v9.6_Final.exe` | 266,817,418 B | `CC42638851D26EFB9710D7517A1DB1EDD2B309AC939D89E775940B9940C5B616` | Inno Setup installer, unsigned |
| `Instalar_Archeon_v9.8_Final.exe` | 267,117,055 B | `59943E06BAE067205A5A88956C1748B78B29C685928BE4E9FAF6A16EA376175D` | Newest installer, unsigned; exact payload extraction blocked |

The expanded workspace is approximately 1.712 GiB. Most of that is not application source: `.venv` is ~695 MB, FFmpeg distribution ~310 MB, `build` ~296 MB, `dist` ~267 MB, and `web` ~267 MB because it contains an installer.

`RECOVERY_MANIFEST.csv` inventories 19,418 supplied files with size and SHA-256 (manifest SHA-256: `B07946E3222D923521542C6155AA42FB6D8258C1A68AD9FB8AA73C8F6B4059FD`). `LEGACY_DEPENDENCIES.csv` records 110 installed distributions and versions recovered from the legacy virtual environment.

## Source inventory

### Core/source files

- `Archeo32n.py`: process bootstrap, Flask routes, login/config UI API, speech loop, TTS queue, pywebview lifecycle and orchestration.
- `archeon_cloud.py`: Firebase/Firestore users, sessions, configuration, memories, tastes, commands, chat and verification codes.
- `archeon_music.py`: yt-dlp discovery, FFmpeg decode, sounddevice output, queueing, autoplay and audio-device monitoring.
- `archeon_neuro.py`, `archeon_reasoner.py`, `archeon_dialog_manager.py`: intent cascade, rule handling, tool bridging and remote-model fallback.
- `archeon_context_memory.py`, `archeon_knowledge.py`: short context and JSON knowledge prototypes.
- `archeon_system.py`: window/system/file/application actions and a local SQLite file index.
- `archeon_vision.py`: screenshot/window context and remote vision-analysis prototype.
- `sistema_predicciones.py`: local habit/prediction prototype.
- `archeon_openrouter.py`: OpenRouter adapter.
- `archeon_updater.py`: unverified remote update flow.
- `archeon_social.py`: source missing; Python 3.10 bytecode exists in `__pycache__` and the PyInstaller archive. Exact source recovery remains partial.

### UI and assets

- `web/dashboard.html` and `web/login.html`: self-contained HTML/CSS/JS interface.
- `web/logo_asitente.png` and `.ico`: recovered visual identity.
- `assets/`: ARCHEON and DZCOMPANY MP4/MP3 intro assets.
- The logo extracted from the v9.6 PyInstaller executable is byte-identical to the loose PNG/ICO.
- The HTML extracted from the v9.6 executable is older than the loose HTML: the loose dashboard adds 256 lines including mini-mode, microphone controls and an application drawer.

### Data/configuration

- `archeon_files.db`: SQLite `file_index(name, path, type, last_seen)`, 978 recovered rows. The row contents were not copied into documentation because they contain local user paths.
- `guest_config.json` and prediction-memory files: local prototype state; excluded from the new checkpoint.
- `.env`, two Firebase service-account JSON files, and a Firebase private credential embedded in `Archeo32n.py`: sensitive and excluded from Git.

## Recovered current behavior

### Desktop/UI

- Flask binds to `0.0.0.0:5000`; pywebview opens `http://127.0.0.1:5000/login`.
- Login, guest mode, registration/recovery, configuration, status, music pause/stop/volume and command endpoints are present.
- The UI polls `/api/status` every 2 seconds and updates its clock every second.
- The app drawer in the loose dashboard is explicitly simulated and therefore must not be represented as a completed feature.

### Voice/audio

- `speech_recognition` continuously holds a `Microphone()` context and calls Google recognition.
- Wake activation is text matching after cloud recognition, so audio is not filtered locally by VAD/wake word first.
- TTS uses a dedicated `pyttsx3` queue/thread.
- `MusicManager` starts an output-device polling thread immediately, checking every 0.5 seconds even when no music is playing.
- FFmpeg is started only for playback, but the full binary is bundled into the monolithic executable.

### AI and intent

- Gemini is initialized during startup; OpenRouter is another fallback.
- `ArcheonReasoner` provides a small enum/regex rule layer; `NeuroCore` combines rules, context, system/vision tools and remote models.
- The design is a useful prototype but tools do not yet have formal schemas, permission declarations, risk levels or verification contracts.

### System/files

- System/application controls, screenshots, file search and status reporting exist.
- `SystemCore` deletes and rebuilds its SQLite index at startup by recursively walking Desktop, Downloads and Documents.
- Destructive actions (empty recycle bin, delete temp files, shutdown/restart, killing processes) lack a central permission/risk layer.

### Cloud

- The supplied source is Firebase, not Supabase. Literal Firestore collections include `users`, `sessions`, `verification_codes`, `memoria`, `gustos`, `comandos`, `chats` and `mensajes`.
- The requested Supabase project `rcgipowzivogyqbuwzlv` could not be inspected: the installed Supabase connector is authenticated to a different account/project and the in-app browser has no Supabase session. No table, user or data from either project was queried or changed.

## Ghost Mode / Music UI Recovery

### What was recovered

- Circular ARCHEON logo/core with concentric animated rings.
- On active music, the core image is replaced by `thumbnail` artwork and receives class `album-mode`.
- `album-mode` uses `animation: spin 10s linear infinite`; pause is implemented with `.paused #core-image.album-mode { animation-play-state: paused; }`, preserving the current approximate rotation angle.
- A compact music widget animates into view, displays a scrolling title, and exposes previous, pause/resume, stop and volume controls.
- The loose dashboard adds `body.mini-mode`: it hides the sidebar, clock, status and menu, scales the visualizer and leaves a small expand button.
- Visual inspection with an inert local preview confirmed idle, full-dashboard, mini-mode and active-music states without starting the legacy backend.

### What the current implementation is not

- Mini-mode is not an independent floating, frameless, transparent Windows window.
- It does not persist monitor, DPI, position, size, always-on-top, click-through or auto-hide settings.
- It has no native media-session integration and no external-player support.
- Album art comes directly from the music result; no embedded-art-first lookup or durable cache hierarchy was found.
- The UI has no event bus; status is driven by 2-second polling.
- Song-change fade/scale transitions, hover/radial controls and short assistant cards are not complete.

### Classification

`KEEP + REFACTOR + ENHANCE`: preserve the visual behavior and identity, replace polling with events, split media/art/state services, and implement a real lightweight orb window. The main WebView should be suspendable/destroyable while a native or very small shared-runtime orb remains active.

## Packaging and performance findings

The v9.6 PyInstaller executable contains broad dependency trees rather than only the runtime paths actually used:

- `Qt5WebEngineCore.dll`: 102,009,328 B uncompressed / 45,852,138 B compressed.
- bundled `ffmpeg.exe`: 99,264,000 B uncompressed / 35,812,188 B compressed.
- `PYZ.pyz`: 16,154,276 B.
- full PyQt5 Qt/QML/plugins, Google/Firebase SDKs and the complete yt-dlp extractor tree are included.

This explains most of the ~267 MB executable. The build specification explicitly collects PyQt5, QtWebEngine, Firebase, Google APIs and many optional modules. A WebView2-only pywebview build should not bundle Qt at all. FFmpeg should be reduced to the required codecs/protocols or packaged as an optional media component.

## Security and stability findings

1. **Critical — rotate secrets:** Firebase private material and API keys were stored in clear text and at least one credential was embedded in source/executable. Treat all supplied keys as compromised; revoke/rotate them before any production use.
2. **Critical — service account in client:** a Firebase Admin service account must not ship in a desktop client. Move privileged operations to a trusted backend and use end-user auth/RLS.
3. **High — network exposure:** Flask binds to all interfaces while several status/music endpoints do not require authentication. Default to loopback; remote access must use an authenticated gateway with pairing and explicit permissions.
4. **High — updater:** downloads and runs an update using `shell=True` without a cryptographic signature/trusted manifest and rollback. Disable until redesigned.
5. **High — permissions:** system/destructive actions have no unified confirmation, risk evaluation or audit layer.
6. **Medium — forced shutdown:** `os._exit(0)` prevents orderly cleanup, cache flush and resource disposal.
7. **Medium — broad exception swallowing:** many bare `except` blocks hide device/network/state failures.
8. **Medium — packaging:** all executables/installers are unsigned, preventing publisher verification and weakening update trust.

## Module disposition

| Area | Status | Decision |
|---|---|---|
| Visual identity and core/orb | Recovered | **KEEP + ENHANCE** |
| Loose dashboard music UI | Recovered, functional prototype | **KEEP + REFACTOR** |
| Loose CSS mini-mode | Partial | **REPLACE implementation; KEEP behavior** |
| Flask local API | Functional but exposed/threaded | **REFACTOR** to loopback event-driven API |
| pywebview | Viable if forced to WebView2 only | **KEEP conditionally**; remove Qt fallback from package |
| Firebase CloudManager | Legacy and unsafe client privilege | **REPLACE** with Supabase user-auth/RLS adapter after schema audit |
| SpeechRecognition/Google loop | Functional prototype, always active | **REPLACE** with lazy AudioManager + local VAD/wake word + pluggable STT |
| pyttsx3/SAPI TTS queue | Useful local fallback | **REFACTOR** behind TTS provider interface |
| MusicManager | Valuable behavior, heavy/busy implementation | **REFACTOR** into internal player, decoder, metadata and session services |
| SystemCore | Useful primitives | **REFACTOR** into permissioned tools; remove startup full scan |
| Reasoner/intent enum | Useful seed | **REFACTOR** into typed intents/tools |
| ContextMemory | Useful seed | **KEEP + REFACTOR** |
| KnowledgeCore | Prototype JSON knowledge | **REPLACE** with consented storage/RAG later |
| VisionCore | Prototype | **REPLACE** with UI Automation first, vision on demand |
| Prediction engine | Experimental, always-running worker | **SUSPEND/REFACTOR**; load only when enabled |
| SocialCore | Bytecode only | **UNKNOWN/PARTIAL**; document behavior before reimplementation |
| Updater | Unsafe | **REMOVE from runtime until REPLACED** |
| Build/venv/FFmpeg distributions in source archive | Reproducibility and size problem | **REMOVE from source control**, reproduce from locked dependencies |

## Recovery limits and next gates

- Exact v9.8 payload extraction remains blocked by the installer archive parser. Safe next options are: obtain the already-installed v9.8 application directory, obtain the v9.8 build/dist folder, or run the installer only inside an isolated Windows Sandbox/VM.
- Supabase schema/RLS/auth/storage documentation remains blocked until the target project is made visible to the connector or the user signs into Supabase in an available browser session.
- Runtime RAM/CPU/GPU/startup baselines for v9.8 were not measured because executing an unsigned installer/application with embedded live credentials and an auto-updater would violate the recovery safety boundary. Static size/process risks are documented; runtime benchmarks begin on the safe reconstructed skeleton.
