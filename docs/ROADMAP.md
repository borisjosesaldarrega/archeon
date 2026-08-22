# ARCHEON Recovery and Reconstruction Roadmap

Statuses: `DONE`, `IN PROGRESS`, `BLOCKED`, `PLANNED`.

## Phase 0 — Recovery and safety

- **DONE:** hash and inventory supplied ZIP, v9.6 executable/installers and v9.8 installer.
- **DONE:** static source/module/dependency/API/background-worker audit.
- **DONE:** extract and compare v9.6 PyInstaller UI/assets with loose files.
- **DONE:** visually verify recovered full UI, mini-mode and music artwork behavior using an inert local preview.
- **DONE:** classify recovered modules and define target architecture/performance budgets.
- **DONE:** exclude secrets/user data/build artifacts and create a Git checkpoint.
- **BLOCKED:** exact v9.8 payload extraction; needs installed files/build output or isolated Windows VM/Sandbox run.
- **BLOCKED:** live Supabase schema/RLS/storage audit; needs target-project authentication.
- **PLANNED:** rotate all Firebase/Google/OpenRouter credentials before any legacy runtime test.

## Phase 1 — Lightweight core foundation

- Create typed configuration, events, module lifecycle and cancellation primitives.
- Implement Tool, Permission, Risk, Audit and Verification contracts.
- Loopback-only async API + authenticated WebSocket event stream.
- Port safe local intents/context first; leave legacy adapters isolated.
- Add startup/resource benchmark harness and CI dependency-size gates.
- Acceptance: no microphone/model/music/vision imports or worker threads at idle.

## Phase 2 — Desktop shell and Ghost Mode

- WebView2-only full UI; eliminate Qt/PyQt packaging.
- Real independent orb window with DPI/multi-monitor recovery.
- Event-driven assistant states, adaptive animation and accessibility controls.
- Suspend/destroy full UI while long-lived Ghost Mode is active.
- Acceptance: meet Ghost Mode CPU/RAM/GPU budgets for a 30-minute idle run.

## Phase 3 — Audio and language

- WASAPI shared-mode AudioManager and device notifications.
- Local VAD and replaceable wake word loaded only when listening is enabled.
- Provider interfaces for STT/TTS, bilingual/mixed-language detection and barge-in.
- Acceptance: coexistence tests with Discord/browser/Teams plus disconnect/Bluetooth/sample-rate recovery.

## Phase 4 — Music/media

- Refactor decoder/output/queue/session/artwork into separate modules.
- Metadata-first artwork cache and smooth pause/change transitions.
- Windows external media sessions; internal/external sources remain distinct.
- Optional minimal codec component and measured quality profiles.

## Phase 5 — Supabase and mobile

- Complete live schema/security audit and reviewed migration plan.
- Replace Firebase Admin client with Supabase user auth/RLS and trusted backend functions only where required.
- Secure QR pairing, revocable devices, LAN-first transport and authenticated relay fallback.
- Streaming mobile STT/TTS/files with explicit permission and size limits.

## Phase 6 — Desktop, browser, terminal and files

- Permissioned Windows tools and safe terminal runner with stdout/stderr/exit verification.
- UI Automation/Accessibility before vision or coordinates.
- Structured browser provider with DOM/accessibility and vision fallback.
- Checkpoints/diffs/rollback for coding and file modifications.

## Phase 7 — Memory, automations and model routing

- User-controlled short/long/semantic/device memory.
- Structured event-based automations; no busy polling.
- ModelProvider/ModelRouter with rules/local tools first and optional local/cloud models.
- Retrieval/evaluation datasets before any fine-tuning work.

## Phase 8 — Plugins and production

- Signed manifests, declared permissions/dependencies and isolated plugin lifecycle.
- Reproducible builds, Authenticode signing, verified updater and rollback.
- Crash reporting with consent/redaction, accessibility/i18n, upgrade tests and release benchmarks.

## Definition of done

A feature is complete only when implementation, tests, error handling, permission behavior, documentation, resource measurements and regression checks all pass. Simulated UI remains labeled `EXPERIMENTAL` and cannot satisfy acceptance.

