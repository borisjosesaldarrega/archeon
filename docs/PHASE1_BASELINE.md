# ARCHEON Phase 1 runnable baseline

Date: 2026-08-21 (America/Guayaquil)

The new application is runnable through `archeon`, while the recovered legacy
tree remains unchanged behind checkpoint `5dcdb89`.

## Original verified runtime

- Core startup: 8–14 ms across the recorded scenarios.
- Headless Core: 33.711 MB working set / 17.930 MB private, 0.0% sampled idle CPU.
- Native Ghost: 46.453 MB working set / 23.117 MB private, 0.0% sampled idle CPU.
- Main WebView2 UI: 487.520 MB working set / 274.095 MB private.
- Local music playback: 543.771 MB working set / 304.918 MB private; playback was
  confirmed by the real `music.started` action.
- Main WebView2 became available in about 0.82 seconds.

The first Ghost implementation reused WebView2 and measured 446.971 MB. It was
replaced before checkpointing with the native transparent implementation above,
reducing the measured working set by about 90%. The full UI still needs WebView2
profiling: its multiprocess cost is material even though no Qt process remains.

CPU percentages for WebView2 include short renderer startup/animation spikes in
the three-second window; longer steady-state sampling is the next measurement.
Per-process GPU counters were unavailable through psutil on this machine, so the
result is explicitly `null`, never estimated. Full data is stored in
`benchmarks/latest.json` and the append-only `benchmarks/history.jsonl`.

## Corrected current sampler

The Windows virtual-environment executable is a launcher. A later run mistakenly
followed that launcher and omitted WebView2; the benchmark now follows the real
PID announced by ARCHEON. The final 2026-08-21 post-voice/media run measured
29.4 MB Core, 39.8 MB Ghost idle, 44.6 MB Ghost + music, 466.3 MB full UI short
idle and 459.0 MB full UI + music. A longer full-UI idle sample measured
457.3 MB and 0.31% CPU. See `UI_FRONTEND_EVALUATION.md`; these figures replace
the incomplete 102 MB graphical sample, not the original 487/544 MB observation.

## Dependency gate

The recovered 110 packages are classified in
`LEGACY_DEPENDENCIES_CLASSIFIED.csv`: 8 REQUIRED, 25 OPTIONAL, 39 REPLACE,
13 REMOVE, and 25 UNKNOWN. UNKNOWN means excluded until a measured feature owner
justifies it. The isolated Phase 1 environment contains only ARCHEON plus nine
runtime/support distributions. Qt, QtWebEngine, Flask, Firebase and AI/audio
model stacks are absent.

## Known external blockers

- Supabase project `rcgipowzivogyqbuwzlv`: provider boundary exists, but schema
  work remains blocked until the correct authenticated dashboard session is
  available. No Firebase schema was guessed.
- v9.8 installer: preserved as evidence; deeper dynamic analysis still needs an
  installed-folder copy or an isolated VM/Sandbox.
