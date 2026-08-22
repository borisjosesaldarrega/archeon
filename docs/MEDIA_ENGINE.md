# ARCHEON MediaEngine

## Selected implementation

Local playback uses `miniaudio` 1.71 with the Windows WASAPI backend. Metadata and embedded artwork use `tinytag` 2.3.0. Pillow 12.3.0 is used only when the native Ghost must render embedded art. All live in the optional `media` dependency group and are imported only by their owning active feature.

This selection avoids the legacy 99 MB FFmpeg binary, NumPy buffers, yt-dlp startup work, a permanent output-device polling thread and external playback processes. The playback and metadata wheels are approximately 274 kB and 37 kB respectively; both projects use the MIT license. The 7.2 MB Pillow wheel is justified only for Ghost artwork and remains unloaded in idle/logo-only mode.

Windows MCI was tested first because it would add no package dependency, but opening the recovered MP3 returned MCI initialization error 277 on this host. It was rejected as an unreliable primary backend rather than hidden behind a fake success state.

## Implemented behavior

- Native desktop file picker with multiple selection; files are played in place and are not uploaded or copied.
- Bounded queue of 256 tracks with play, pause, resume, stop, seek, volume, next and previous.
- MP3, WAV, FLAC and Ogg/Vorbis decoding in streaming mode.
- Metadata and duration read on demand; title and artist have local fallbacks.
- Embedded artwork is extracted atomically into the local data cache, capped at 4 MB per image and served through a runtime-token-protected loopback URL.
- The ARCHEON orb switches to artwork when present, rotates while playing, preserves the CSS rotation state while paused and transitions between covers.
- No decoder, output device, media watcher or metadata dependency is loaded while idle.
- During active playback there is one miniaudio/WASAPI device plus one event-blocked end watcher. Stop and application shutdown close the decoder/device, join the watcher and leave no `archeon-media-*` threads.
- Starting voice while music is active pauses music first so recognition is not fed by ARCHEON's own playback.

AAC/M4A is not claimed as supported by this backend. Adding an FFmpeg fallback would materially increase package size and process complexity, so it remains a separately measured future option.

## Validation on the current Windows host

Recorded 2026-08-21 (America/Guayaquil):

- Direct WASAPI smoke: play, pause, resume and close succeeded on the recovered MP3.
- Full engine smoke at 15% volume: playback reached 640 ms, pause succeeded, seek moved to 1.2 s, resume reached 1.68 s, and stop left the backend unloaded with zero media watcher threads.
- Web UI guest flow emitted real `music.started`, `music.paused`, `music.resumed` and `music.stopped` states; the visual state changed to `state-paused` during pause.
- A temporary MP3 with an embedded logo produced a 35,531-byte PNG cover through `/media/art/<id>` with the correct MIME type and PNG signature. The temporary test track was then deleted.
- The automated suite covers lazy idle state, queue controls, seek, volume, device selection handoff, next/previous, event-driven auto-advance and deterministic release.

## Still to measure

Run the revised process-tree benchmark for Ghost + music and full UI + music, including private memory, CPU, handles and the exact WebView2 process family. Test long MP3/FLAC/Ogg files and output-device removal. A native Windows media-session adapter can be added later, but must remain optional and event-driven.
