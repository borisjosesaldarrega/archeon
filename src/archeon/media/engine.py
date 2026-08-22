"""Event-driven local queue and playback engine."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent

from .backend import MiniAudioPlayer
from .metadata import MetadataReader, Track


class MediaState(StrEnum):
    STOPPED = "stopped"
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
        player_factory: Callable[..., MiniAudioPlayer] = MiniAudioPlayer,
    ) -> None:
        super().__init__("media")
        self._events = events
        self._metadata = MetadataReader(data_dir / "media-art")
        self._output_device_provider = output_device_provider
        self._player_factory = player_factory
        self._queue: list[Track] = []
        self._index = -1
        self._state = MediaState.STOPPED
        self._volume = 0.7
        self._player: MiniAudioPlayer | None = None
        self._ended = Event()
        self._watch_stop = Event()
        self._watcher: Thread | None = None
        self._lock = RLock()

    @property
    def state(self) -> MediaState:
        with self._lock:
            return self._state

    @property
    def backend_loaded(self) -> bool:
        return self._player is not None

    @property
    def current(self) -> Track | None:
        with self._lock:
            return self._queue[self._index] if 0 <= self._index < len(self._queue) else None

    def status(self) -> dict[str, Any]:
        track = self.current
        with self._lock:
            player = self._player
            return {
                "available": all(importlib.util.find_spec(name) is not None for name in ("miniaudio", "tinytag")),
                "state": self._state.value,
                "backend_loaded": player is not None,
                "queue_length": len(self._queue),
                "queue_index": self._index,
                "position_ms": player.position_ms if player is not None else 0,
                "volume": self._volume,
                "track": track.public() if track else None,
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

    def play(self, index: int | None = None) -> dict[str, Any]:
        with self._lock:
            if index is not None:
                if not 0 <= index < len(self._queue):
                    raise ValueError("invalid_media_index")
                if index != self._index:
                    self._close_player_locked()
                self._index = index
            track = self.current
            if track is None:
                raise RuntimeError("media_queue_empty")
            if self._state is MediaState.PAUSED and self._player is not None:
                self._player.play()
                self._state = MediaState.PLAYING
                event = "music.resumed"
            else:
                self._open_current_locked(0)
                event = "music.started"
            payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
        self._events.publish(event, payload, source="media")
        return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._state is not MediaState.PLAYING or self._player is None:
                return self.status()
            self._player.pause()
            self._state = MediaState.PAUSED
            payload = self.status()
        self._events.publish("music.paused", payload, source="media")
        return payload

    def resume(self) -> dict[str, Any]:
        return self.play()

    def stop_playback(self) -> dict[str, Any]:
        with self._lock:
            self._stop_locked(clear_queue=False, publish=False)
            payload = self.status()
        self._events.publish("music.stopped", payload, source="media")
        return payload

    def seek(self, position_ms: int) -> dict[str, Any]:
        with self._lock:
            track = self.current
            if track is None:
                raise RuntimeError("media_queue_empty")
            target = max(0, min(int(position_ms), track.duration_ms))
            was_playing = self._state is MediaState.PLAYING
            self._open_current_locked(target, start=was_playing)
            if not was_playing:
                self._state = MediaState.PAUSED
            payload = self.status()
        self._events.publish("music.seeked", payload, source="media")
        return payload

    def set_volume(self, value: float) -> dict[str, Any]:
        normalized = max(0.0, min(1.0, float(value)))
        with self._lock:
            self._volume = normalized
            if self._player is not None:
                self._player.set_volume(normalized)
            payload = self.status()
        self._events.publish("music.volume.changed", {"volume": normalized}, source="media")
        return payload

    def next(self) -> dict[str, Any]:
        return self._move(1)

    def previous(self) -> dict[str, Any]:
        return self._move(-1)

    def _move(self, offset: int) -> dict[str, Any]:
        with self._lock:
            if not self._queue:
                raise RuntimeError("media_queue_empty")
            self._index = (self._index + offset) % len(self._queue)
            self._open_current_locked(0)
            track = self.current
            payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
        self._events.publish("music.started", payload, source="media")
        return self.status()

    def _open_current_locked(self, seek_ms: int, *, start: bool = True) -> None:
        track = self.current
        assert track is not None
        self._close_player_locked(stop_watcher=True)
        self._ended.clear()
        self._watch_stop.clear()
        player = self._player_factory(output_device_id=self._output_device_provider())
        player.set_volume(self._volume)
        player.open(str(track.path), seek_ms=seek_ms, on_end=self._ended.set)
        self._player = player
        self._state = MediaState.PLAYING if start else MediaState.PAUSED
        if start:
            player.play()
        self._watcher = Thread(target=self._watch_end, name="archeon-media-end", daemon=False)
        self._watcher.start()

    def _watch_end(self) -> None:
        self._ended.wait()
        if self._watch_stop.is_set():
            return
        with self._lock:
            if self._watch_stop.is_set() or self._state is not MediaState.PLAYING:
                return
            if self._index + 1 < len(self._queue):
                self._index += 1
                self._open_current_locked(0)
                track = self.current
                payload = track.public() | {"queue_index": self._index, "queue_length": len(self._queue)}
                self._events.publish("music.started", payload, source="media")
            else:
                self._close_player_locked()
                self._state = MediaState.STOPPED
                self._events.publish("music.stopped", source="media")

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
        self._state = MediaState.STOPPED
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
