"""Deterministic component startup and reverse-order shutdown."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from threading import RLock
from typing import Iterable


class ComponentState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ManagedComponent(ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self._state = ComponentState.CREATED
        self._lifecycle_lock = RLock()

    @property
    def state(self) -> ComponentState:
        return self._state

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._state is ComponentState.RUNNING:
                return
            if self._state not in {ComponentState.CREATED, ComponentState.STOPPED}:
                raise RuntimeError(f"cannot start {self.name} from {self._state}")
            self._state = ComponentState.STARTING
            try:
                self._start()
            except Exception:
                self._state = ComponentState.FAILED
                raise
            self._state = ComponentState.RUNNING

    def stop(self) -> None:
        with self._lifecycle_lock:
            if self._state in {ComponentState.CREATED, ComponentState.STOPPED}:
                self._state = ComponentState.STOPPED
                return
            if self._state is ComponentState.STOPPING:
                return
            self._state = ComponentState.STOPPING
            try:
                self._stop()
            except Exception:
                self._state = ComponentState.FAILED
                raise
            self._state = ComponentState.STOPPED

    @abstractmethod
    def _start(self) -> None: ...

    @abstractmethod
    def _stop(self) -> None: ...


class LifecycleManager:
    def __init__(self, components: Iterable[ManagedComponent] = ()) -> None:
        self._components = list(components)
        self._started: list[ManagedComponent] = []

    def add(self, component: ManagedComponent) -> None:
        if self._started:
            raise RuntimeError("cannot add components after lifecycle startup")
        self._components.append(component)

    def start(self) -> None:
        try:
            for component in self._components:
                component.start()
                self._started.append(component)
        except Exception:
            self.stop(suppress_errors=True)
            raise

    def stop(self, *, suppress_errors: bool = False) -> None:
        first_error: Exception | None = None
        for component in reversed(self._started):
            try:
                component.stop()
            except Exception as error:  # shutdown must continue for later components
                first_error = first_error or error
        self._started.clear()
        if first_error is not None and not suppress_errors:
            raise first_error

