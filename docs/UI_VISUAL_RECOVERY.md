# ARCHEON visual recovery

## Evidence used

The implementation is based directly on the recovered `web/login.html`,
`web/dashboard.html`, `web/logo_asitente.png`, `web/logo_asitente.ico`, the
legacy route/state logic in `Archeo32n.py`, and the previously rendered inert
legacy preview. It is not based on the temporary Phase 1 shell.

The old shortcut points to `C:\Program Files (x86)\Archeon AI\Archeo32n.exe`,
but that installation directory no longer exists. No registered Archeon
installation was found in the standard uninstall registry locations. The v9.8
installer remains in Downloads and was not executed on the host.

## Recovered visual language

| Element | Recovered behavior |
|---|---|
| Base | Near-black `#09090b` / `#050505` canvas with radial cyan light |
| Primary accent | Electric cyan `#00f3ff` |
| Listening/error | Magenta-red `#ff2a6d` |
| Music | Green `#00ff88` |
| Panels | Dark translucent glass, subtle white border, large soft shadow |
| Type | Segoe UI for UI; light uppercase display text; Consolas for system labels |
| Login | Centered access panel, cyan left rail, widely spaced ARCHEON wordmark |
| Dashboard | Clock at upper left, menu at upper right, circular core in center |
| Orb | Three concentric rings around the recovered logo |
| Listening | Red core/rings and amplitude response |
| Music | Album image replaces logo, core grows, image rotates like a disc |
| Pause | Rotation keeps its angle through `animation-play-state: paused` |
| Player | Bottom glass widget with title, pause and stop controls |

## Implemented in the new UI

- Restored access gateway with separate welcome, login and registration views.
- Functional local guest session and functional development login/register.
- Session-protected local commands/actions and logout.
- ES/EN locale resources; new UI labels use translation keys.
- Restored legacy palette, panel silhouette, logo treatment, clock, sidebar,
  three-ring core, state colors and bottom music treatment.
- UI states are driven by Event Bus event names. No timer simulates voice.
- Voice control is visibly disabled and labelled experimental until a real
  capture/STT/TTS backend is verified.
- Idle rings do not rotate, preserving near-zero idle CPU; animation starts only
  for processing, speaking, listening or music events.

## Deliberate differences

- Firebase calls, inline secrets and SMTP verification logic were not copied.
- The development provider stores only scrypt-derived password hashes locally.
- Supabase auth is behind a provider and assumes no custom tables or schema.
- Legacy 0.5-second status polling was replaced by SSE events.
- Legacy CSS mini-mode remains replaced by the native Ghost window.
- Constant idle ring animation was removed for the performance budget.

## Still pending

- Safe dynamic observation of the v9.8 installer in Sandbox/VM.
- Real microphone amplitude, VAD, STT, TTS and barge-in events.
- Full MediaEngine metadata, queue, artwork cache and seek behavior.
- Screenshots of every v9.8 state for exact spacing/transition comparison.
