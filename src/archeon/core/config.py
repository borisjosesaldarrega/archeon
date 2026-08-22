"""Versioned, atomic, non-secret local configuration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from .lifecycle import ManagedComponent


@dataclass(slots=True)
class PerformanceConfig:
    profile: str = "balanced"
    animation_fps: int = 60
    idle_animation: bool = False


@dataclass(slots=True)
class GhostConfig:
    enabled: bool = False
    always_on_top: bool = True
    click_through: bool = False
    size: int = 112
    opacity: float = 1.0
    position_x: int | None = None
    position_y: int | None = None


@dataclass(slots=True)
class AudioConfig:
    enabled: bool = False
    backend: str = "wasapi_shared"
    input_device_id: str | None = None
    output_device_id: str | None = None


@dataclass(slots=True)
class AppConfig:
    schema_version: int = 1
    locale: str = "es"
    theme: str = "dark"
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    ghost: GhostConfig = field(default_factory=GhostConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    permissions: dict[str, str] = field(default_factory=dict)


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(base) / "ARCHEON" if base else Path.home() / ".archeon"


class ConfigurationManager(ManagedComponent):
    def __init__(self, path: Path | None = None) -> None:
        super().__init__("configuration")
        self.path = path or default_data_dir() / "config.json"
        self._config = AppConfig()
        self._lock = RLock()

    @property
    def config(self) -> AppConfig:
        return self._config

    def _start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._config = self._decode(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.save()

    def _stop(self) -> None:
        self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(asdict(self._config), ensure_ascii=False, indent=2)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix="config-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_path = Path(temporary.name)
            os.replace(temp_path, self.path)

    def set_permission(self, permission: str, state: str) -> None:
        with self._lock:
            self._config.permissions[permission] = state
            self.save()

    @staticmethod
    def _decode(data: dict[str, Any]) -> AppConfig:
        profile = str(data.get("performance", {}).get("profile", "balanced")).lower()
        if profile not in {"eco", "balanced", "performance"}:
            profile = "balanced"
        fps_default = 30 if profile == "eco" else 60
        fps = int(data.get("performance", {}).get("animation_fps", fps_default))
        ghost_size = max(64, min(256, int(data.get("ghost", {}).get("size", 112))))
        opacity = max(0.2, min(1.0, float(data.get("ghost", {}).get("opacity", 1.0))))
        return AppConfig(
            schema_version=1,
            locale=str(data.get("locale", "es")),
            theme=str(data.get("theme", "dark")),
            performance=PerformanceConfig(
                profile=profile,
                animation_fps=max(1, min(60, fps)),
                idle_animation=bool(data.get("performance", {}).get("idle_animation", False)),
            ),
            ghost=GhostConfig(
                enabled=bool(data.get("ghost", {}).get("enabled", False)),
                always_on_top=bool(data.get("ghost", {}).get("always_on_top", True)),
                click_through=bool(data.get("ghost", {}).get("click_through", False)),
                size=ghost_size,
                opacity=opacity,
                position_x=data.get("ghost", {}).get("position_x"),
                position_y=data.get("ghost", {}).get("position_y"),
            ),
            audio=AudioConfig(
                enabled=bool(data.get("audio", {}).get("enabled", False)),
                backend=str(data.get("audio", {}).get("backend", "wasapi_shared")),
                input_device_id=data.get("audio", {}).get("input_device_id"),
                output_device_id=data.get("audio", {}).get("output_device_id"),
            ),
            permissions={str(key): str(value) for key, value in data.get("permissions", {}).items()},
        )

