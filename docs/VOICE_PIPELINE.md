# ARCHEON Voice Pipeline

## Implemented path

The first production-oriented local path is:

`WASAPI shared capture -> WebRTC VAD -> Vosk small Spanish -> Orchestrator -> Windows SAPI`

- Capture is 16 kHz, mono, signed 16-bit PCM in 20 ms frames.
- Windows WASAPI is always opened in shared, non-exclusive mode with format conversion enabled.
- A bounded 48-frame callback queue prevents unbounded memory growth.
- WebRTC VAD keeps a 200 ms pre-roll and ends an utterance after 700 ms of silence.
- Waiting for speech is capped at 8 seconds and an utterance at 12 seconds.
- Vosk is imported and its model is loaded only after speech is captured, then released after the cycle.
- SAPI/COM is imported only when ARCHEON actually speaks.
- The voice worker is cancellable and joined during shutdown; audio ownership returns to `AudioManager`.
- Microphone use is granted only for the active application session after the explicit Listen action.
- Transcription events are streamed only after a valid local ARCHEON session exists.

The initial STT language is Spanish. The UI is bilingual and SAPI selects a matching Spanish or English installed voice, but an English STT model is not bundled yet. This is intentional: another model should be added only after its storage, memory, latency and accuracy are measured.

## Optional installation

Voice dependencies are isolated from the base package:

```powershell
python -m pip install -e ".[voice]"
```

The official small Spanish Vosk model must exist at:

```text
models/vosk-model-small-es-0.42/
```

The `models/` directory is ignored by Git so large model assets are not accidentally committed. Packaging must fetch or bundle the reviewed model explicitly and verify its checksum.

## Validation on the current Windows host

Recorded 2026-08-21 (America/Guayaquil):

- WASAPI found three input devices and selected the Windows default input.
- A 0.5-second capture produced 25 valid 20 ms frames and released the stream.
- Windows SAPI exposed Microsoft Sabina (Spanish) and Microsoft Zira (English); Spanish speech completed successfully.
- A SAPI-generated Spanish sample was transcribed exactly as `estado del sistema` by Vosk, then the model reference was released.
- Idle headless measurement after the integration: 33.875 MB average working set, 17.953 MB average private memory, 0.0% sampled CPU, 16.935 ms Core startup, two Python processes in the benchmark process tree.
- The automated suite verifies that `sounddevice`, `vosk` and `comtypes` are absent from `sys.modules` while voice is idle.

The WebView2 figures in that short benchmark run are not accepted as a UI baseline because the harness did not observe the expected WebView2 child processes. Re-run the graphical benchmark after correcting its process-tree discovery.

## Next measurements

Before release, measure live microphone recognition over a fixed phrase set: model-load latency, listening CPU, peak/private RAM, end-of-speech latency, transcription accuracy, TTS latency, handles and memory after five repeated cycles. Compare Vosk against whisper.cpp only in BALANCED/PERFORMANCE profiles; keep the winner justified by measured accuracy per resource used.
