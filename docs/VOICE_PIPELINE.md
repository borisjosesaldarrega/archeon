# ARCHEON Voice Pipeline

## Implemented path

The first production-oriented local path is:

`WASAPI shared capture -> WebRTC VAD -> Vosk small Spanish -> Orchestrator -> Windows SAPI`

- Capture is 16 kHz, mono, signed 16-bit PCM in 20 ms frames.
- Windows WASAPI is always opened in shared, non-exclusive mode with format conversion enabled.
- A bounded 48-frame callback queue prevents unbounded memory growth.
- WebRTC VAD keeps a 200 ms pre-roll. ECO/BALANCED/PERFORMANCE adjust VAD
  aggressiveness, end silence (600/700/800 ms) and maximum utterance
  (10/12/15 s) through the central catalog in `voice/catalog.py`.
- Vosk is imported and its model is loaded only after speech is captured, then released after the cycle.
- SAPI/COM is imported only when ARCHEON actually speaks.
- The voice worker is cancellable and joined during shutdown; audio ownership returns to `AudioManager`.
- Microphone use is granted only for the active application session after the explicit Listen action.
- Transcription events are streamed only after a valid local ARCHEON session exists.
- The settings dialog enumerates the real WASAPI inputs, installed SAPI voices and
  SAPI outputs. Profile, input, voice, output, rate, volume and barge-in are
  validated and persisted; the next cycle reads them without restarting Core.
- While SAPI speaks, the optional barge-in monitor opens WASAPI shared capture,
  waits through a 400 ms guard and requires four voiced frames out of five before
  stopping TTS and feeding the captured phrase into the next assistant turn.

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
- A real low-volume TTS/barge-in test completed in 2.389 s with no false
  interruption, no captured residual audio and the input stream released.
- All three installed WASAPI inputs were changed in one running process and each
  produced 23–24 valid frames in 0.5 s before clean release. See
  `MICROPHONE_COMPATIBILITY.md`.
- Idle headless measurement after the integration: 33.875 MB average working set, 17.953 MB average private memory, 0.0% sampled CPU, 16.935 ms Core startup, two Python processes in the benchmark process tree.
- The automated suite verifies that `sounddevice`, `vosk` and `comtypes` are absent from `sys.modules` while voice is idle.

That early WebView2 sample was incomplete because it followed the venv launcher.
The corrected full-interface figures are in `UI_FRONTEND_EVALUATION.md`.

### Real-provider voice benchmark

The corrected PID sampler produced `benchmarks/voice-latest.json`:

| Scenario | Duration | Working set avg / peak | Private avg / peak | CPU avg | Result |
|---|---:|---:|---:|---:|---|
| Listening | 3063 ms | 32.6 / 33.4 MB | 16.6 / 17.0 MB | 4.18% | shared stream released |
| Vosk STT | 839 ms | 103.6 / 162.7 MB | 451.4 / 658.3 MB | 99.96% | exact phrase; model released |
| Windows SAPI TTS | 2859 ms | 57.0 / 59.7 MB | 26.0 / 26.9 MB | 11.42% | completed |
| Full local cycle | 3826 ms | 154.9 / 169.0 MB | 489.2 / 529.6 MB | 23.60% | completed; audio released |

CPU can exceed 100% when native recognition uses more than one logical core.
Windows private/commit accounting includes the Vosk model mapping and can exceed
resident working set; both metrics are retained rather than conflated. Listening
includes stream/import startup in a short three-second interval, so it is not an
idle-background percentage. There is no microphone polling outside an active
voice or barge-in interval.

## Next measurements

Before release, measure live microphone recognition over a fixed phrase set: model-load latency, listening CPU, peak/private RAM, end-of-speech latency, transcription accuracy, TTS latency, handles and memory after five repeated cycles. ECO/BALANCED/PERFORMANCE intentionally share the one tested Vosk model today; adding larger model IDs without measured assets would create fake profiles. Compare Vosk against whisper.cpp only when an actual candidate model is packaged and measured.
