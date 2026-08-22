"""Manifest-first plugins that do not import code during application startup."""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent


_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


class Plugin(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    version: str
    entrypoint: str
    enabled: bool = False


class PluginManager(ManagedComponent):
    def __init__(self, events: EventBus, directory: Path) -> None:
        super().__init__("plugins")
        self._events = events
        self._directory = directory
        self._manifests: dict[str, PluginManifest] = {}
        self._active: dict[str, Plugin] = {}
        self._lock = RLock()

    @property
    def loaded_count(self) -> int:
        return len(self._active)

    def scan(self) -> tuple[PluginManifest, ...]:
        """Read small JSON manifests only; importing remains activation-only."""
        discovered: dict[str, PluginManifest] = {}
        if not self._directory.exists():
            return ()
        for path in sorted(self._directory.glob("*/plugin.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            plugin_id = str(data.get("id", ""))
            entrypoint = str(data.get("entrypoint", ""))
            if not _ID.fullmatch(plugin_id) or ":" not in entrypoint:
                continue
            discovered[plugin_id] = PluginManifest(
                plugin_id=plugin_id,
                version=str(data.get("version", "0")),
                entrypoint=entrypoint,
                enabled=bool(data.get("enabled", False)),
            )
        with self._lock:
            self._manifests = discovered
        return tuple(discovered.values())

    def activate(self, plugin_id: str) -> None:
        with self._lock:
            if plugin_id in self._active:
                return
            manifest = self._manifests[plugin_id]
            module_name, attribute = manifest.entrypoint.split(":", 1)
            factory = getattr(importlib.import_module(module_name), attribute)
            plugin = factory()
            plugin.start()
            self._active[plugin_id] = plugin
            self._events.publish("plugin.started", {"id": plugin_id}, source="plugins")

    def deactivate(self, plugin_id: str) -> None:
        with self._lock:
            plugin = self._active.pop(plugin_id, None)
            if plugin is not None:
                plugin.stop()
                self._events.publish("plugin.stopped", {"id": plugin_id}, source="plugins")

    def _start(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)

    def _stop(self) -> None:
        for plugin_id in tuple(reversed(self._active)):
            self.deactivate(plugin_id)
        self._manifests.clear()
