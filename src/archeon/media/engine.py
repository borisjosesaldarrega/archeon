"""Event-driven local queue and playback engine."""

from __future__ import annotations

import importlib.util
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent

from .backend import MiniAudioPlayer, is_online_media_path
from .codecs import CodecRouter
from .metadata import MetadataReader, Track
from .providers import MediaSearchResult


class MediaState(StrEnum):
    STOPPED = "stopped"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"


class MediaEngine(ManagedComponent):
    MAX_QUEUE = 256

    def __init__(
        self,
        events: EventBus,
        data_dir: Path,
        *,
        output_device_provider=lambda: None,
        player_factory: Callable[..., MiniAudioPlayer] | None = None,
        codec_router: CodecRouter | None = None,
        dj_enabled_provider: Callable[[], bool] = lambda: False,
        dj_strategy_provider: Callable[[], str] = lambda: "mixed",
        continuation_provider: Callable[[Track, tuple[str, ...], str], MediaSearchResult | None] | None = None,
    ) -> None:
        super().__init__("media")
        self._events = events
        self._metadata = MetadataReader(data_dir / "media-art")
        self._output_device_provider = output_device_provider
        self._player_factory = player_factory
        self._codec_router = codec_router or CodecRouter(data_dir / "runtimes")
        self._dj_enabled_provider = dj_enabled_provider
        self._dj_strategy_provider = dj_strategy_provider
        self._continuation_provider = continuation_provider
        self._queue: list[Track] = []
        self._index = -1
        # ManagedComponent owns ``_state`` for its lifecycle.  Playback must
        # use an independent field or start() changes "stopped" to "running"
        # even when no track/player exists.
        self._playback_state = MediaState.STOPPED
        self._volume = 0.7
        self._player: Any | None = None
        self._playback_start_position_ms = 0
        self._last_progress_at = 0.0
        self._last_progress_position_ms = 0
        self._pending_play_event = "music.started"
        self._web_player_active = False
        self._web_position_ms = 0
        self._ended = Event()
        self._watch_stop = Event()
        self._watcher: Thread | None = None
        self._lock = RLock()
        self._history: list[str] = []
        self._rejected: set[str] = set()
        self._dj_blocked = False

    @property
    def state(self) -> MediaState:
        with self._lock:
            return self._playback_state

    @property
    def backend_loaded(self) -> bool:
        return self._player is not None

    @property
    def current(self) -> Track | None:
        with self._lock:
            return self._queue[self._index] if 0 <= self._index < len(self._queue) else None

    def current_stream_source(self) -> str | Path | None:
        """Return the current verified source for the token-protected mobile proxy."""
        with self._lock:
            track = self._queue[self._index] if 0 <= self._index < len(self._queue) else None
            if track is None or track.playback_kind != "native_audio" or not track.path:
                return None
            return track.path

    def status(self) -> dict[str, Any]:
        track = self.current
        with self._lock:
            player = self._player
            web_media = bool(track and track.playback_kind == "official_web")
            position_ms = player.position_ms if player is not None else self._web_position_ms if web_media else 0
            playable_source = bool(track and str(track.path).strip())
            clock_advanced = bool(player is not None and position_ms > self._playback_start_position_ms)
            progress_recent = bool(
                player is not None and self._last_progress_at > 0
                and time.monotonic() - self._last_progress_at <= 5.0
                and self._last_progress_position_ms >= position_ms - 1_000
            )
            if web_media:
                clock_advanced = self._web_player_active and position_ms > self._playback_start_position_ms
                progress_recent = self._web_player_active and self._last_progress_at > 0 and time.monotonic() - self._last_progress_at <= 5.0
            active_backend = player is not None or (web_media and self._web_player_active)
            playback_verified = bool(
                self._playback_state is MediaState.PLAYING and track is not None
                and playable_source and active_backend and clock_advanced and progress_recent
            )
            return {
                "available": all(importlib.util.find_spec(name) is not None for name in ("miniaudio", "tinytag")),
                "state": self._playback_state.value,
                "backend_loaded": player is not None,
                "codec_backend": getattr(player, "codec_backend", None) if player is not None else None,
                "queue_length": len(self._queue),
                "queue_index": self._index,
                "position_ms": position_ms,
                "volume": self._volume,
                "track": track.public() if track else None,
                "history": list(self._history[-50:]),
                "rejected": list(sorted(self._rejected))[-50:],
                "dj_mode": bool(self._dj_enabled_provider()),
                "dj_strategy": str(self._dj_strategy_provider()),
                "playback_evidence": {
                    "active_track": track is not None,
                    "playable_source": playable_source,
                    "active_backend": active_backend,
                    "clock_advanced": clock_advanced,
                    "frames_advancing": progress_recent,
                    "verified_playing": playback_verified,
                },
            }

    def devices(self) -> list[dict[str, Any]]:
        return MiniAudioPlayer.devices()

    def load(self, paths: list[Path], *, append: bool = False) -> list[dict[str, object]]:
        if not paths or len(paths) > self.MAX_QUEUE:
            raise ValueError("invalid_media_queue")
        tracks = [self._metadata.read(path) for path in paths]
        with self._lock:
            if append:
                if len(self._queue) + len(tracks) > self.MAX_QUEUE:
                    raise ValueError("media_queue_too_large")
                self._queue.extend(tracks)
                if self._index < 0:
                    self._index = 0
            else:
                self._stop_locked(clear_queue=True, publish=False)
                self._queue = tracks
                self._index = 0
        self._events.publish("music.queue.changed", self.status(), source="media")
        return [track.public() for track in tracks]

    def load_results(self, results: list[MediaSearchResult], *, append: bool = False) -> list[dict[str, object]]:
        if not results or len(results) > self.MAX_QUEUE:
            raise ValueError("invalid_media_queue")
        if all(result.local_path for result in results):
            return self.load([Path(result.local_path or "") for result in results], append=append)
        tracks = [
            Track(
                id=result.id, path=result.stream_url or result.source_url or "", title=result.title,
                artist=result.artist, album=result.album, duration_ms=result.duration_ms,
                artwork_id=self._metadata.register_remote_artwork(result.artwork_url), provider=result.provider,
                source_url=result.source_url, license_url=result.license_url,
                artist_source=result.artist_source,
                playback_kind=result.playback_kind, external_id=result.external_id,
            )
            for result in results
            if result.stream_url or (result.playback_kind == "official_web" and result.source_url)
        ]
        if not tracks:
            raise ValueError("media_results_not_playable")
        with self._lock:
            if append:
                if len(self._queue) + len(tracks) > self.MAX_QUEUE:
                    raise ValueError("media_queue_too_large")
                self._queue.extend(tracks)
                if self._index < 0:
                    self._index = 0
            else:
                self._stop_locked(clear_queue=True, publish=False)
                self._queue = tracks
                self._index = 0
        self._events.publish("music.queue.changed", self.status(), source="media")
        return [track.public() for track in tracks]

    def play(self, index: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._dj_blocked = False
            if index is not None:
                if not 0 <= index < len(self._queue):
                    raise ValueError("invalid_media_index")
                if index != self._index:
                    self._close_player_locked()
                self._index = index
            track = self.current
            if track is None:
                raise RuntimeError("media_queue_empty")
            if track.playback_kind == "official_web":
                if self._playback_state in {MediaState.PLAYING, MediaState.BUFFERING} and self._web_player_active:
                    return self.status()
                self._pending_play_event = "music.resumed" if self._playback_state is MediaState.PAUSED else "music.started"
                self._playback_start_position_ms = self._web_position_ms
                self._playback_state = MediaState.BUFFERING
                payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
                command = "play" if self._web_player_active else "load"
                if track.id not in self._history:
                    self._history.append(track.id); self._history = self._history[-100:]
                self._events.publish("music.web.requested", payload, source="media") if command == "load" else self._events.publish("music.web.command", {"command": command}, source="media")
                return self.status()
            # Play is deliberately idempotent. UI clicks, media keys and voice
            # commands can arrive close together; reopening an already active
            # decoder here would restart the song from zero.
            if self._playback_state in {MediaState.PLAYING, MediaState.BUFFERING} and self._player is not None:
                return self.status()
            if self._playback_state is MediaState.PAUSED and self._player is not None:
                self._playback_start_position_ms = self._player.position_ms
                self._pending_play_event = "music.resumed"
                self._playback_state = MediaState.BUFFERING
                self._player.play()
                event = "music.buffering" if self._playback_state is MediaState.BUFFERING else None
            else:
                self._pending_play_event = "music.started"
                self._open_current_locked(0)
                # A synchronous/test backend may already have emitted the
                # verified start through _on_player_progress.
                event = "music.buffering" if self._playback_state is MediaState.BUFFERING else None
            payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
            if track.id not in self._history:
                self._history.append(track.id)
                self._history = self._history[-100:]
        if event is not None:
            self._events.publish(event, payload, source="media")
        return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            track = self.current
            if track is not None and track.playback_kind == "official_web":
                if self._playback_state not in {MediaState.PLAYING, MediaState.BUFFERING}:
                    return self.status()
                self._events.publish("music.web.command", {"command": "pause"}, source="media")
                return self.status()
            if self._playback_state not in {MediaState.PLAYING, MediaState.BUFFERING} or self._player is None:
                return self.status()
            self._player.pause()
            self._playback_state = MediaState.PAUSED
            payload = self.status()
        self._events.publish("music.paused", payload, source="media")
        return payload

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if self._playback_state is not MediaState.PAUSED:
                return self.status()
        return self.play()

    def stop_playback(self) -> dict[str, Any]:
        with self._lock:
            self._dj_blocked = True
            if self.current is not None and self.current.playback_kind == "official_web":
                self._events.publish("music.web.command", {"command": "stop"}, source="media")
            self._stop_locked(clear_queue=False, publish=False)
            payload = self.status()
        self._events.publish("music.stopped", payload, source="media")
        return payload

    def seek(self, position_ms: int) -> dict[str, Any]:
        with self._lock:
            track = self.current
            if track is None:
                raise RuntimeError("media_queue_empty")
            if track.playback_kind == "official_web":
                target = max(0, min(int(position_ms), track.duration_ms)) if track.duration_ms else max(0, int(position_ms))
                self._playback_start_position_ms = target
                self._events.publish("music.web.command", {"command": "seek", "position_ms": target}, source="media")
                return self.status()
            if isinstance(track.path, str) and is_online_media_path(track.path) and position_ms:
                raise RuntimeError("online_media_seek_unavailable")
            target = max(0, min(int(position_ms), track.duration_ms))
            was_playing = self._playback_state in {MediaState.PLAYING, MediaState.BUFFERING}
            self._open_current_locked(target, start=was_playing)
            if not was_playing:
                self._playback_state = MediaState.PAUSED
            payload = self.status()
        self._events.publish("music.seeked", payload, source="media")
        return payload

    def set_volume(self, value: float) -> dict[str, Any]:
        normalized = max(0.0, min(1.0, float(value)))
        with self._lock:
            self._volume = normalized
            if self._player is not None:
                self._player.set_volume(normalized)
            if self.current is not None and self.current.playback_kind == "official_web":
                self._events.publish("music.web.command", {"command": "volume", "volume": normalized}, source="media")
            payload = self.status()
        self._events.publish("music.volume.changed", {"volume": normalized}, source="media")
        return payload

    def next(self) -> dict[str, Any]:
        with self._lock:
            has_next = self._index + 1 < len(self._queue)
            current = self.current
        if has_next:
            return self._move(1)
        if current is not None and self._dj_enabled_provider() and self._continuation_provider is not None:
            result = self._continuation_provider(current, tuple(self._history + list(self._rejected)), str(self._dj_strategy_provider()))
            if result is not None:
                self.load_results([result], append=False)
                return self.play()
        self.stop_playback()
        return self.status()

    def previous(self) -> dict[str, Any]:
        with self._lock:
            if self._index <= 0:
                return self.status()
        return self._move(-1)

    def reject(self, track_id: str) -> None:
        value = str(track_id).strip()
        if not value:
            return
        with self._lock:
            self._rejected.add(value)
            if len(self._rejected) > 100:
                self._rejected = set(list(sorted(self._rejected))[-100:])

    def _move(self, offset: int) -> dict[str, Any]:
        with self._lock:
            if not self._queue:
                raise RuntimeError("media_queue_empty")
            self._index = max(0, min(len(self._queue) - 1, self._index + offset))
            if self.current is not None and self.current.playback_kind == "official_web":
                self._close_player_locked(stop_watcher=True)
                self._web_player_active = False
                self._web_position_ms = 0
                use_web_player = True
            else:
                use_web_player = False
            if use_web_player:
                track = self.current
                payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
            else:
                self._open_current_locked(0)
                track = self.current
                payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
        if use_web_player:
            return self.play()
        if self._playback_state is MediaState.BUFFERING:
            self._events.publish("music.buffering", payload, source="media")
        return self.status()

    def _open_current_locked(self, seek_ms: int, *, start: bool = True) -> None:
        track = self.current
        assert track is not None
        self._close_player_locked(stop_watcher=True)
        self._ended.clear()
        self._watch_stop.clear()
        output_device_id = self._output_device_provider()
        if self._player_factory is not None:
            player = self._player_factory(output_device_id=output_device_id)
        else:
            player = self._codec_router.create_player(
                str(track.path), provider=track.provider, output_device_id=output_device_id,
            )
        player.set_volume(self._volume)
        player.open(
            str(track.path), seek_ms=seek_ms, on_end=self._ended.set,
            on_progress=lambda position: self._on_player_progress(player, position),
        )
        self._player = player
        self._playback_start_position_ms = seek_ms
        self._last_progress_at = 0.0
        self._last_progress_position_ms = seek_ms
        self._playback_state = MediaState.BUFFERING if start else MediaState.PAUSED
        if start:
            player.play()
        self._watcher = Thread(target=self._watch_end, name="archeon-media-end", daemon=False)
        self._watcher.start()

    def _watch_end(self) -> None:
        self._ended.wait()
        if self._watch_stop.is_set():
            return
        with self._lock:
            if self._watch_stop.is_set() or self._playback_state not in {MediaState.PLAYING, MediaState.BUFFERING}:
                return
            if self._index + 1 < len(self._queue):
                self._index += 1
                self._open_current_locked(0)
                track = self.current
                payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
                if self._playback_state is MediaState.BUFFERING:
                    self._events.publish("music.buffering", payload, source="media")
                return
            current = self.current
            dj_enabled = bool(self._dj_enabled_provider()) and not self._dj_blocked and self._continuation_provider is not None
            if not dj_enabled or current is None:
                self._close_player_locked()
                self._playback_state = MediaState.STOPPED
                self._events.publish("music.stopped", source="media")
                return
            self._close_player_locked()
            self._playback_state = MediaState.STOPPED
        result = self._continuation_provider(current, tuple(self._history + list(self._rejected)), str(self._dj_strategy_provider()))
        if result is None:
            self._events.publish("music.stopped", source="media")
            return
        with self._lock:
            if self._dj_blocked:
                return
            track = Track(
                id=result.id, path=result.stream_url or result.local_path or "", title=result.title,
                artist=result.artist, album=result.album, duration_ms=result.duration_ms,
                artwork_id=self._metadata.register_remote_artwork(result.artwork_url), provider=result.provider,
                source_url=result.source_url, license_url=result.license_url,
                artist_source=result.artist_source,
            )
            if not track.path or track.id in self._history or track.id in self._rejected:
                self._events.publish("music.stopped", source="media")
                return
            self._queue.append(track)
            self._queue = self._queue[-self.MAX_QUEUE:]
            self._index = len(self._queue) - 1
            self._history.append(track.id); self._history = self._history[-100:]
            self._open_current_locked(0)
            payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue), "dj": True}
        if self._playback_state is MediaState.BUFFERING:
            self._events.publish("music.buffering", payload, source="media")

    def _on_player_progress(self, player: Any, position_ms: int) -> None:
        """Promote BUFFERING only after the active backend delivers frames."""
        event: str | None = None
        payload: dict[str, Any] | None = None
        with self._lock:
            if player is not self._player:
                return
            self._last_progress_at = time.monotonic()
            self._last_progress_position_ms = int(position_ms)
            if self._playback_state is not MediaState.BUFFERING:
                return
            if int(position_ms) <= self._playback_start_position_ms:
                return
            self._playback_state = MediaState.PLAYING
            event, self._pending_play_event = self._pending_play_event, "music.started"
            track = self.current
            if track is not None:
                payload = track.public() | {
                    "queue_index": self._index, "queue_length": len(self._queue),
                    "position_ms": int(position_ms), "playback_verified": True,
                }
        if event and payload:
            self._events.publish(event, payload, source="media")

    def report_web_state(self, state: str, position_ms: int = 0, duration_ms: int = 0) -> dict[str, Any]:
        """Accept verified state only from the visible official web player."""
        event: str | None = None
        payload: dict[str, Any] | None = None
        with self._lock:
            track = self.current
            if track is None or track.playback_kind != "official_web":
                raise RuntimeError("official_web_session_unavailable")
            normalized = str(state).casefold()
            self._web_player_active = normalized in {"buffering", "playing", "paused"}
            self._web_position_ms = max(0, int(position_ms))
            if normalized == "playing" and self._web_position_ms > self._last_progress_position_ms:
                self._last_progress_at = time.monotonic()
                self._last_progress_position_ms = self._web_position_ms
            if duration_ms > 0 and track.duration_ms <= 0:
                track = Track(
                    id=track.id, path=track.path, title=track.title, artist=track.artist,
                    album=track.album, duration_ms=int(duration_ms), artwork_id=track.artwork_id,
                    artwork_url=track.artwork_url, provider=track.provider, source_url=track.source_url,
                    license_url=track.license_url, artist_source=track.artist_source,
                    playback_kind=track.playback_kind, external_id=track.external_id,
                )
                self._queue[self._index] = track
            if normalized == "playing" and self._web_position_ms > self._playback_start_position_ms:
                self._playback_state = MediaState.PLAYING
                event, self._pending_play_event = self._pending_play_event, "music.started"
                payload = track.public() | {"position_ms": self._web_position_ms, "playback_verified": True}
            elif normalized == "paused":
                self._playback_state = MediaState.PAUSED
                event, payload = "music.paused", self.status()
            elif normalized == "ended":
                self._playback_state = MediaState.STOPPED
                self._web_player_active = False
                event, payload = "music.stopped", self.status()
            else:
                self._playback_state = MediaState.BUFFERING
            result = self.status()
        if event and payload is not None:
            self._events.publish(event, payload, source="media")
        return result

    def _close_player_locked(self, *, stop_watcher: bool = False) -> None:
        if stop_watcher:
            self._watch_stop.set()
            self._ended.set()
        player, self._player = self._player, None
        watcher, self._watcher = self._watcher, None
        if player is not None:
            player.close()
        if stop_watcher and watcher is not None and watcher is not current_thread():
            watcher.join(timeout=2.0)
            if watcher.is_alive():
                raise RuntimeError("media watcher did not stop")

    def _stop_locked(self, *, clear_queue: bool, publish: bool) -> None:
        self._close_player_locked(stop_watcher=True)
        self._playback_state = MediaState.STOPPED
        self._playback_start_position_ms = 0
        self._last_progress_at = 0.0
        self._last_progress_position_ms = 0
        self._web_player_active = False
        self._web_position_ms = 0
        if clear_queue:
            self._queue.clear()
            self._index = -1
        if publish:
            self._events.publish("music.stopped", source="media")

    def artwork(self, artwork_id: str) -> tuple[str, bytes] | None:
        return self._metadata.artwork(artwork_id)

    def _start(self) -> None:
        pass

    def _stop(self) -> None:
        with self._lock:
            self._stop_locked(clear_queue=True, publish=False)
