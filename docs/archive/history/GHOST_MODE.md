# Native Ghost Mode

The Ghost remains a Tk/Win32 window and never starts WebView2. It shares the existing Core, EventBus, VoicePipeline and MediaEngine; it does not create a second Core or playback process.

## Controls and states

- Drag moves the orb and its last coordinates are persisted through the existing configuration lifecycle.
- A single click plays, pauses or resumes the current queue.
- A double-click opens the full interface without also triggering the single-click action.
- Right-click opens a localized ES/EN native menu for play/pause, previous, next, stop, full interface and exit.
- Real voice events change the ring for listening, transcribing/thinking, speaking and error. Real microphone levels pulse the listening ring.
- Real media events switch to green playing/paused states.
- Embedded cover art is decoded only when present. Twenty-four small rotation frames are prepared once, then Tk swaps references at 8 FPS. Pause cancels the scheduled frame and resume continues from the same index.
- Returning from Ghost restores the application session through a one-use in-memory continuation. The session token is not written to `localStorage` or disk.

Pillow is isolated in the optional `media` dependencies and imported only when the Ghost actually receives embedded artwork. The 7.2 MB Windows wheel replaces no base dependency and is not loaded for idle/logo-only Ghost mode.

## Measurements on this host

Recorded 2026-08-21 (America/Guayaquil):

| Scenario | Working set | Private memory | CPU | Processes |
|---|---:|---:|---:|---:|
| Ghost idle inspection | 39.8 MiB | not sampled in that pass | near-idle | 1 Python, 0 WebView2 |
| Ghost + muted music + rotating embedded art | 48.4 MiB | 27.6 MiB | 0.5% over 3 s | 1 Python, 0 WebView2 |

The first rotating-art implementation rendered with Pillow ten times per second and measured 6.2% CPU. It was rejected and replaced by precalculated frames; the accepted implementation measured 0.5% CPU with less than 1 MiB additional working set in the comparison run.

Both smoke runs exited automatically with code 0 and left no tested process. The temporary cover-art track was deleted after measurement.
