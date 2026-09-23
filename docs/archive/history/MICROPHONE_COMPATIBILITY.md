# Microphone compatibility — WASAPI shared

Recorded 2026-08-21 on the current Windows host. ARCHEON always requests
`WasapiSettings(exclusive=False, auto_convert=True)`, uses 16 kHz mono 16-bit
frames and owns the stream only for an active listening or barge-in interval.

## Automated host smoke

One running `AudioManager` selected each available input in sequence without a
Core restart. Audio content was discarded immediately and never written to disk.

| Input | 20 ms frames in 0.5 s | Released |
|---|---:|---:|
| Wireless Controller microphone (index 28) | 23 | yes |
| Microphone V8 (index 29) | 23 | yes |
| Steam Streaming Microphone (index 30) | 24 | yes |

Edge and Opera were running throughout the smoke test and no device-busy,
sample-rate or release error occurred. This proves shared coexistence with the
browser processes present on this host; it does not prove that a browser tab was
simultaneously publishing the microphone.

Discord and OBS were not running and were not launched automatically, so their
rows remain explicitly unverified rather than reported as passes.

| Combination | Host result |
|---|---|
| ARCHEON + Edge/Opera running | PASS — shared captures completed and released |
| ARCHEON + active browser microphone tab | MANUAL TEST REQUIRED |
| ARCHEON + Discord call | NOT AVAILABLE ON HOST |
| ARCHEON + OBS recording | NOT AVAILABLE ON HOST |

## Manual release checklist

For each available application, start its microphone meter/call/recording, then
start and stop five ARCHEON voice cycles while watching both meters. Confirm no
`device occupied` error, no audible format change, continued audio in the other
application, correct ARCHEON transcription, and that the Windows privacy meter
returns to its previous state after ARCHEON stops. Repeat once after changing
the selected ARCHEON input in Settings without restarting the application.
