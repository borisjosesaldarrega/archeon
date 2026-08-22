# ARCHEON Experience Foundation — iteration report

Date: 2026-08-21 (America/Guayaquil)

## 1. Functions actually implemented

- Reconstructed ES/EN ARCHEON access screen with login, registration and local guest entry.
- Provider-based sessions, logout and local development accounts without Firebase or mandatory Supabase.
- Event-driven dashboard and orb states: idle, listening, transcribing/thinking, executing, speaking, music, paused and error.
- Lazy WASAPI shared capture, WebRTC VAD, local Vosk Spanish STT and Windows SAPI TTS.
- Runtime voice settings for ECO/BALANCED/PERFORMANCE, microphone, voice, TTS output, rate, volume and barge-in.
- Local `MediaEngine`: file selection, queue, play/pause/resume/stop, seek, volume, next/previous, metadata and embedded artwork.
- Native Ghost with real voice states, media controls, album art, optimized rotation and one-use return session.
- Corrected process-tree and real-provider benchmark tooling.

## 2. Visual evidence

The access screen, main guest dashboard and real voice-settings dialog were
captured and visually inspected in the Codex task. The implemented source and
visual rationale are in `UI_VISUAL_RECOVERY.md`.

## 3–5. Legacy differences, recovered and recreated

Recovered: cyan/black identity, ARCHEON logo, access hierarchy, central orb,
music-to-cover behavior, circular motion language, Ghost concept and assistant
state vocabulary. Recreated on the new Core: auth/session implementation,
responsive accessible markup, bilingual strings, real event bridge, permissioned
microphone action, lightweight media backend and native Ghost controls.

Not copied: Firebase, eager startup modules, Qt/QtWebEngine, FFmpeg bundle,
startup recursive indexing, polling loops, duplicate assistant processes and
embedded secrets. The v9.8 installer was not executed on the host, so no claim is
made that pixel geometry or every transition is an exact runtime copy.

## 6–7. STT and TTS choices

Vosk small Spanish was selected because its official small model is practical
for offline CPU use and can be unloaded after a cycle. It transcribed the fixed
Spanish sample exactly. WebRTC VAD was selected over Silero to avoid a neural
runtime. Windows SAPI provides real local TTS, installed voices and device
selection without shipping another model. Optional dependencies remain isolated.

## 8. WASAPI compatibility

All three installed inputs captured in shared, non-exclusive mode and released
after a live device change in one process. Edge and Opera were running. Discord
and OBS were not running, so active-call/recording coexistence remains manual.
See `MICROPHONE_COMPATIBILITY.md`.

## 9. Benchmarks

Final general matrix (`benchmarks/latest.json`, 2 s warm-up / 3 s sample):

| Scenario | Working set avg | Private avg | CPU avg | Processes |
|---|---:|---:|---:|---:|
| Core headless | 29.4 MB | 18.1 MB | 0.0% | 1 |
| Ghost idle | 39.8 MB | 22.1 MB | 0.0% | 1 |
| Ghost + music | 44.6 MB | 24.5 MB | 2.99% | 1 |
| Full UI short idle | 466.3 MB | 257.2 MB | 9.88% | 7 |
| Full UI + music | 459.0 MB | 248.0 MB | 4.43% | 7 |

The separate 5 s warm-up / 10 s full-UI sample measured 457.3 MB and 0.31%
average CPU. WebView2 accounts for six of seven processes. GPU remains `null`
because the host sampler exposes no per-process GPU counter.

Voice results are in `benchmarks/voice-latest.json`: listening 33.4 MB peak and
3.06 s; STT 162.7 MB working-set peak and 839 ms; TTS 59.7 MB peak and 2.86 s;
full cycle 169.0 MB peak and 3.83 s. Every worker exited with code 0.

## 10–11. Automated and manual tests

- 30 automated tests pass; Python compilation succeeds for `src`, `tools` and `tests`.
- Real 0.5 s WASAPI smoke on all three inputs; every stream released.
- Real SAPI output and Vosk transcription (`estado del sistema`).
- Real low-volume barge-in monitor smoke: no false trigger and clean release.
- Real media play/pause/seek/resume/stop and embedded-cover retrieval.
- Native Ghost idle/music auto-exit tests left no tested process.
- Access, guest dashboard and voice settings were visually inspected in the browser.

## 12–14. UI, Ghost and Voice consumption

The full UI remains the main resource debt at ~457 MB steady working set. A
non-functional Tk/Win32 full-window feasibility probe measured 27.0 MB, but it
does not justify a migration by itself. WinUI runtimes exist, while no .NET SDK
or WinUI template is installed. The measured decision is documented in
`UI_FRONTEND_EVALUATION.md`.

Ghost stays well below the 70 MB goal and creates no WebView2 process. Voice and
media load only on demand; microphone, playback backend and Vosk model are
released after use.

## 15. Commits

- `4b63880` auth and local/provider sessions
- `b2335ea` reconstructed access/dashboard identity
- `710bfdd` lazy local voice pipeline
- `537fbc6` lazy local media engine
- `8e11af8` native Ghost media/assistant states
- `170dc79` voice profiles, settings and barge-in
- `17a9121` voice/Ghost/frontend measurements

## 16. Open problems

- Full WebView2 RAM is still high; keep profiling or build a truly comparable
  native prototype before changing frameworks.
- English STT is honestly unavailable until a measured English/multilingual model is packaged.
- Supabase project/schema work awaits the correct authenticated session; no schema was invented.
- Active Discord, OBS and browser-publishing microphone tests require those applications and user-controlled sessions.
- v9.8 dynamic behavioral capture still requires Windows Sandbox/VM or an installed-folder copy.
- GPU utilization was attempted but cannot be attributed with the current sampler.
- A real speaker/microphone acoustic barge-in test with a person speaking over
  TTS remains necessary across headsets and speakers; the architecture and
  synthetic/failure tests are implemented.
