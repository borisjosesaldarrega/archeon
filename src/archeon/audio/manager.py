"""Audio ownership without opening devices or importing drivers at startup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Protocol

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent


class AudioMode(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PLAYING = "playing"


@dataclass(frozen=True, slots=True)
class AudioSessionConfig:
    host_api: str = "WASAPI"
    shared: bool = True
    exclusive: bool = False
    sample_rate: int = 48_000
    channels: int = 1
    block_ms: int = 20


class AudioBackend(Protocol):
    def open(self, config: AudioSessionConfig) -> None: ...
    def close(self) -> None: ...


BackendFactory = Callable[[], AudioBackend]


class AudioManager(ManagedComponent):
    """Owns one lazy backend and guarantees release on shutdown.

    The initial policy is deliberately WASAPI shared mode. No backend module,
    microphone handle, worker or model exists until ``acquire`` is requested.
    """

    def __init__(self, events: EventBus) -> None:
        super().__init__("audio")
        self._events = events
        self._factories: dict[str, BackendFactory] = {}
        self._backend: AudioBackend | None = None
        self._mode = AudioMode.IDLE
        self._lock = RLock()

    @property
    def mode(self) -> AudioMode:
        return self._mode

    @property
    def backend_loaded(self) -> bool:
        return self._backend is not None

    def register_backend(self, name: str, factory: BackendFactory) -> None:
        if not name or name in self._factories:
            raise ValueError(f"invalid or duplicate audio backend: {name}")
        self._factories[name] = factory

    def acquire(self, mode: AudioMode, *, backend: str = "wasapi_shared") -> None:
        if mode is AudioMode.IDLE:
            raise ValueError("acquire requires an active audio mode")
        with self._lock:
            if self._backend is not None:
                raise RuntimeError("an audio session is already active")
            try:
                factory = self._factories[backend]
            except KeyError as error:
                raise RuntimeError(f"audio backend is unavailable: {backend}") from error
            candidate = factory()
            config = AudioSessionConfig()
            if not config.shared or config.exclusive:
                raise RuntimeError("ARCHEON audio policy requires shared non-exclusive mode")
            candidate.open(config)
            self._backend = candidate
            self._mode = mode
            self._events.publish("audio.acquired", {"mode": mode.value}, source="audio")

    def release(self) -> None:
        with self._lock:
            backend, previous = self._backend, self._mode
            self._backend = None
            self._mode = AudioMode.IDLE
            if backend is not None:
                backend.close()
                self._events.publish(
                    "audio.released", {"mode": previous.value}, source="audio"
                )

    def _start(self) -> None:
        self._mode = AudioMode.IDLE

    def _stop(self) -> None:
        self.release()
        self._factories.clear()
