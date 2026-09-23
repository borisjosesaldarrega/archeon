"""Portable application paths and read-only packaged resource lookup."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping


def _user_root(environment: Mapping[str, str]) -> Path:
    base = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
    return Path(base).expanduser() / "ARCHEON" if base else Path.home() / ".archeon"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """All writable locations are user-owned and separate from installation files."""

    install_dir: Path
    package_dir: Path
    data_dir: Path
    cache_dir: Path
    default_model_dir: Path

    @classmethod
    def discover(
        cls,
        *,
        data_dir: Path | None = None,
        package_dir: Path | None = None,
        executable: Path | None = None,
        environment: Mapping[str, str] | None = None,
        frozen: bool | None = None,
    ) -> "AppPaths":
        env = os.environ if environment is None else environment
        package = (package_dir or Path(__file__).resolve().parents[1]).resolve()
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        executable_path = (executable or Path(sys.executable)).resolve()
        install = executable_path.parent if is_frozen else package.parents[1]
        root = Path(data_dir or env.get("ARCHEON_DATA_DIR") or _user_root(env)).expanduser().resolve()
        cache = Path(env.get("ARCHEON_CACHE_DIR") or root / "cache").expanduser().resolve()
        models = Path(env.get("ARCHEON_MODELS_DIR") or root / "models").expanduser().resolve()
        return cls(install.resolve(), package, root, cache, models)

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def secure_dir(self) -> Path:
        return self.data_dir / "secure"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def runtimes_dir(self) -> Path:
        """Versioned optional sidecars, separate from transient runtime state."""
        return self.data_dir / "runtimes"

    def model_dir(self, configured: str | Path | None = None) -> Path:
        if configured:
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                candidate = self.data_dir / candidate
            return candidate.resolve()
        return self.default_model_dir

    def ensure_writable_dirs(self, configured_model_dir: str | Path | None = None) -> None:
        for path in (
            self.data_dir,
            self.cache_dir,
            self.logs_dir,
            self.secure_dir,
            self.plugins_dir,
            self.runtime_dir,
            self.runtimes_dir,
            self.model_dir(configured_model_dir),
        ):
            path.mkdir(parents=True, exist_ok=True)


class ResourceManager:
    """Resolve immutable package resources without consulting the working directory."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def path(self, relative: str) -> Path:
        normalized = PurePosixPath(relative.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("invalid_resource_path")
        candidate = self.paths.package_dir.joinpath(*normalized.parts).resolve()
        if candidate != self.paths.package_dir and self.paths.package_dir not in candidate.parents:
            raise ValueError("invalid_resource_path")
        return candidate

    @property
    def ui_dir(self) -> Path:
        return self.path("ui")

    def ui(self, name: str) -> Path:
        return self.path(f"ui/{name}")

    def asset(self, name: str) -> Path:
        """Return a packaged asset, with a source-tree fallback for development."""
        packaged = self.ui(name)
        if packaged.exists():
            return packaged
        normalized = PurePosixPath(name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("invalid_resource_path")
        assets_dir = (self.paths.install_dir / "assets").resolve()
        candidate = assets_dir.joinpath(*normalized.parts).resolve()
        if candidate != assets_dir and assets_dir not in candidate.parents:
            raise ValueError("invalid_resource_path")
        return candidate
