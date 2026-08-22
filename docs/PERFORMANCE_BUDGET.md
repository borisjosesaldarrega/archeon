# ARCHEON Performance Budget

These are provisional engineering gates, not claims about the legacy executable. Measure on at least one modest 4-core/8-GB Windows machine and one current development machine.

| Scenario | ECO target | BALANCED target |
|---|---:|---:|
| Core + Ghost idle working set | <= 80 MB | <= 110 MB |
| Full UI idle working set, all ARCHEON processes | <= 150 MB | <= 200 MB |
| Idle CPU, 5-minute average | <= 0.3% total | <= 0.5% total |
| Idle GPU | 0% average; event-only spikes | 0% average; event-only spikes |
| Cold start to usable Ghost/UI | <= 2.5 s | <= 2.0 s |
| Local intent/UI feedback p95 | <= 200 ms | <= 150 ms |
| Ghost music animation | 30 FPS cap | 60 FPS cap |
| Background network while idle | 0 periodic requests except scheduled sync/update with backoff | same |

Listening, STT, TTS, music and model budgets will be baselined per provider/hardware; no single number is honest before implementations are selected. Each benchmark records wall time, process tree, private/working set, CPU time, GPU engine usage, I/O bytes, handles/threads and request latency.

The first local voice implementation and its host validation are recorded in
`VOICE_PIPELINE.md`. Its dependencies and model remain optional and lazy; the
graphical numbers from the 2026-08-21 short benchmark are excluded until the
WebView2 process-tree sampler is corrected.

## Measurement protocol

1. Clean boot or documented steady-state machine.
2. Release build, fixed performance profile, same sample media/input.
3. Record cold start five times; report median and p95/max.
4. Record idle for 10 minutes after a 2-minute warm-up.
5. Run listening, one local intent, one cloud intent, TTS, music and Ghost transitions separately.
6. Stop the feature and verify memory, handles, threads, subprocesses and device ownership return near baseline.
7. Store results by commit/build; fail CI/release gates on material regression until explained.

## Immediate regression guards

- Deny PyQt/QtWebEngine, local-model runtimes, OpenCV and full ML frameworks in the base package unless a reviewed module explicitly requires them.
- No `while True` polling loop without blocking wait/notification, cancellation and a measured justification.
- No heavy module import in process bootstrap.
- No duplicate Core, FFmpeg or audio capture processes.
- Bounded queues/caches with observable hit rate, size and eviction.
- UI animations pause when hidden, minimized, static or outside an active state.
