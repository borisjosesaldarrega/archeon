# Local neural voice provider evaluation

Review date: 2026-08-23. This is a candidate review only: no runtime or voice model was downloaded or added to production.

| Candidate | Product fit | License/commercial gate | Footprint/languages | Decision |
|---|---|---|---|---|
| Windows SAPI | Already local, lazy, selectable output, lowest integration cost | Uses voices installed/licensed by Windows or the user | No ARCHEON model footprint; quality depends on installed voices | Keep as required base provider |
| sherpa-onnx + individually approved Piper-format voice | Native ONNX-oriented runtime and provider isolation are compatible with lazy load/unload | Runtime declares Apache-2.0; every model must have its own durable license receipt | Spanish/English depend on selected model; `es_ES-davefx-medium` is about 63.2 MB and marked MIT by its publisher | Best benchmark candidate after legal/hash review |
| Piper current upstream | Fast and multilingual, with Spanish and English voices | Current engine is GPL-3.0; unsuitable as a mandatory embedded dependency for a closed product without a deliberate licensing decision. Voice licenses are separate | Typical medium Spanish reference voice about 63 MB | Do not integrate as mandatory runtime |
| Kokoro-82M | Higher naturalness potential | Reference model is Apache-2.0 | Reference weights about 327 MB and the reviewed official card is English; sherpa multilingual listing reviewed is Chinese+English, not Spanish | Reject for the first Spanish milestone; too large/incomplete language fit |
| RHVoice | Very small, Windows/SAPI compatible, active Spanish work | Main engine GPL-2.0 and individual voice/license review still required | Compact statistical synthesis; generally less natural than neural TTS | Optional user-installed SAPI voice only, not bundled |

## Required benchmark gate

Before adding any optional neural provider:

1. Verify exact model card, source URL, immutable revision and SHA-256.
2. Confirm commercial redistribution for runtime, weights, training/voice rights and generated audio.
3. Measure package increase, cold load, first audio, real-time factor, CPU, private RAM, quality in Spanish/English and complete unload.
4. Compare against SAPI on the Ryzen 5 5600GT while the desktop remains responsive.
5. Keep the provider optional and downloadable; ARCHI must still speak through SAPI without it.

## Primary references

- https://github.com/OHF-Voice/piper1-gpl
- https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md
- https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_ES/davefx/medium
- https://k2-fsa.github.io/sherpa/onnx/tts/index.html
- https://github.com/k2-fsa/sherpa-onnx
- https://huggingface.co/hexgrad/Kokoro-82M
- https://github.com/RHVoice/RHVoice
- https://rhvoice.org/languages/
