# ARCHEON Current Architecture

## Runtime topology

```text
Archeo32n.exe (PyInstaller one-file)
├─ startup updater thread
├─ Firebase Admin client + maintenance thread
├─ Gemini/OpenRouter clients
├─ speech-recognition microphone thread
├─ pyttsx3 TTS thread
├─ prediction worker thread
├─ SystemCore startup file-index thread
├─ MusicManager device-polling thread
├─ Flask threaded server on 0.0.0.0:5000
└─ pywebview window
   └─ HTML/CSS/JS dashboard polling /api/status every 2 seconds
```

Music playback adds a DJ thread, recommendation threads, an FFmpeg subprocess, a pipe-reader thread, an audio-output thread and a sounddevice stream.

## Startup path

1. Import and configure remote SDKs and global paths.
2. Start update check.
3. Construct `AsistenteVirtual`.
4. Initialize Firebase Admin and maintenance.
5. Start TTS.
6. Construct MusicManager and start 0.5-second audio-device polling.
7. Construct Social/Neuro/System modules; SystemCore starts file indexing.
8. Initialize Gemini and speech recognizer.
9. Start prediction and continuous microphone threads.
10. Start Flask, wait one second, open pywebview.

This startup sequence eagerly loads almost every subsystem and explains slow startup, high resident memory and background activity.

## UI/API boundary

The UI is a pair of self-contained HTML files served by Flask. State is serialized by `/api/status`; commands use REST endpoints. There is no WebSocket/event stream. Authentication uses a custom token header, while some endpoints are unauthenticated. The host binds to all network interfaces.

## Module coupling

- `AsistenteVirtual` owns concrete Firebase, music, social, neuro, speech and TTS instances.
- Managers call back into the assistant object and inspect one another's mutable properties.
- Intent results are dictionaries with implicit keys instead of typed contracts.
- UI status reads internal manager state directly.
- Permission, audit and risk behavior is scattered or absent.

## Storage

- Firestore/Firebase Admin is the main cloud layer in supplied source.
- SQLite stores only a local file index and has no primary key or useful index.
- JSON stores prediction memory/knowledge/configuration.
- Secrets are loaded from `.env`, JSON and embedded source.

## Resource behavior

- Continuous microphone ownership and cloud STT attempt.
- Polling: UI 2 s, device output 0.5 s, clock 1 s; several worker loops use sleeps.
- Full recursive file index starts automatically.
- QtWebEngine, FFmpeg, Firebase/Google stacks and yt-dlp are bundled in one file.
- Shutdown ends with `os._exit(0)`, bypassing normal cleanup.

## Known functionality status

| Capability | Current state |
|---|---|
| Login/config/session | Firebase prototype |
| Voice wake/command | Cloud recognition loop; no local VAD/wake-word gate |
| TTS | Local SAPI through pyttsx3 |
| Music | yt-dlp + FFmpeg + sounddevice, internal player only |
| Ghost Mode | Loose-HTML CSS mini-mode, not a real floating window |
| Desktop/system | Direct pyautogui/ctypes/subprocess actions |
| File search | Startup SQLite scan of common folders |
| Vision | Screenshot + remote model prototype |
| Browser | Opens/searches URLs; no structured browser engine |
| Mobile | No recoverable production implementation in supplied source |
| Supabase | Not present in supplied source; target project not yet audited |
| Plugins | No manifest/permission lifecycle |

