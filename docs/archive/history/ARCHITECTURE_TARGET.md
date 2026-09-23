# ARCHEON Target Architecture

## Design constraints

1. One core process by default; optional worker processes only for crash-prone/heavy modules.
2. Zero remote model, vision, FFmpeg, microphone or media-session work until requested/enabled.
3. Event-driven state; no constant UI or device polling where Windows notifications exist.
4. Every tool declares permissions, risk, input/output schema, timeout, cancellation and verification.
5. The desktop client never contains privileged database credentials.
6. Features may be installed/enabled independently; inactive modules release resources.

## Proposed topology

```text
Windows Host
├─ Core process
│  ├─ Orchestrator
│  ├─ typed Event Bus
│  ├─ lazy Module Registry
│  ├─ Intent + Context + Memory
│  ├─ Tool/Permission/Audit engines
│  ├─ Configuration + Secret Store
│  └─ loopback HTTP/WebSocket gateway
├─ Full UI: WebView2, created on demand
├─ Ghost Orb: lightweight independent window
└─ optional workers, started on demand
   ├─ audio/STT
   ├─ vision/OCR
   └─ local model runtime
```

The first reconstruction should remain Python to preserve working logic and reduce rewrite risk. Use pywebview only with the installed Edge WebView2 runtime; explicitly exclude PyQt/QtWebEngine from packaging. The local server should be a small async ASGI layer (Starlette/uvicorn or measured equivalent) bound to `127.0.0.1`, with WebSocket events. If measurements show the Python orb cannot meet the Ghost budget, move only the Windows host/orb to a small native helper while keeping the core protocol stable.

## Core contracts

### Event

```text
Event(type, timestamp, source, correlation_id, payload, sensitivity)
```

Bounded queues, backpressure and coalescing are required. High-rate levels (audio amplitude/progress) must be sampled only while visible and at a profile-specific rate.

### Tool

```text
ToolManifest
  id, version, description
  input_schema, output_schema
  permissions[], risk_level
  timeout, cancellable
  resource_class
  supports_rollback, checkpoint_policy
  execute(context, input) -> result
  verify(context, result) -> verification
```

### Module lifecycle

```text
DISCOVERED -> LOADING -> READY -> ACTIVE -> SUSPENDED -> STOPPED
                            \-> FAILED
```

Modules expose `start`, `suspend`, `resume`, `stop` and health/resource snapshots. Import factories lazily; do not import heavy SDKs in module top-level code.

## Subsystems

- **Orchestrator:** resolves intent, plans tool calls, requests permissions, executes, verifies and reports.
- **PermissionEngine:** denied / ask / session / persistent grants, plus mandatory confirmation for destructive/admin actions.
- **PermissionEngine:** granular screen, mouse, keyboard, application, browser, filesystem, terminal, camera, microphone and device grants; never a single implicit "full control" grant.
- **AudioManager:** WASAPI shared-mode devices and notifications, local VAD/wake word gate, lazy STT/TTS providers, barge-in and deterministic resource cleanup.
- **MusicEngine:** internal player separated from Windows Global System Media Transport Controls; decoder subprocess only during playback; bounded buffers and cached artwork.
- **GhostModeManager:** consumes core events; manages an independent window, DPI/monitor recovery, always-on-top/click-through escape path and adaptive rendering.
- **FileEngine:** on-demand search first; Windows Search/USN notifications when enabled; no recursive scan at every startup.
- **DesktopControl:** UI Automation/Accessibility first, native APIs second, vision third, coordinates last.
- **BrowserEngine:** structured DOM/accessibility provider; vision fallback only when needed.
- **ModelRouter:** local/rules/tools before remote model; provider adapters loaded only for selected requests.
- **Model providers:** the Core imports only a provider contract. Local, llama.cpp, ONNX, Ollama and future ARCHEON models are first-class; OpenAI/Gemini/Anthropic adapters remain optional and obey `cloud_allowed`.
- **MemoryEngine:** short-term in memory; user-consented long-term/semantic/device stores with view/edit/delete/export.
- **Device/Mobile gateway:** temporary pairing token, revocable device credentials, LAN-first encrypted channel and authenticated relay fallback.

## Ghost Mode design

- Independent, frameless, transparent window; persisted logical position per monitor/DPI and guaranteed on-screen recovery.
- Destroy or suspend the full WebView when entering long-lived Ghost Mode.
- Idle is static: no animation timer; event-driven repaint only.
- Listening/speaking levels are sampled and coalesced; music rotation caps at 30 FPS in ECO and 60 FPS otherwise.
- Album art lookup: embedded metadata -> provider/session art -> disk cache -> generated fallback. Cache by content hash with size/LRU limits.
- External media uses Windows media-session notifications; no aggressive polling.

## Data and security

- Supabase end-user auth with publishable client key only.
- RLS ownership policies on every exposed user-data table; privileged functions in an unexposed schema and narrowly granted.
- Windows Credential Manager/DPAPI for refresh tokens and provider secrets.
- Local audit log redacts secrets and sensitive content, supports rotation and user export.
- Signed release manifest, Authenticode-signed binaries, hash verification, staged update and rollback.

## Packaging strategy

- Reproducible clean environment with locked direct dependencies.
- Source control excludes virtual environments, build directories, DB/user state, installers and third-party distributions.
- Base package: core, UI, permissions, config and small local rules only.
- Optional components: media codecs, local STT/wake word, vision/OCR and local-model runtimes.
- Generate a PyInstaller dependency report in CI and fail the build if Qt/PyQt or other denied trees reappear.

## Verification gates

Every feature needs unit tests, integration tests, failure/cancellation tests, permission tests and resource measurements. A UI control may ship only when its backend capability is real, or it must be labeled `EXPERIMENTAL/PARTIAL/BLOCKED`.
