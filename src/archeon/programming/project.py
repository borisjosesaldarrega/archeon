"""Cheap marker-based project detection with no language server at idle."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    root: Path
    kinds: tuple[str, ...]
    markers: tuple[str, ...]
    entrypoints: tuple[str, ...]
    suggested_command: tuple[str, ...]
    git: bool
    package_manager: str | None = None
    test_framework: str | None = None
    build_system: str | None = None
    virtual_environment: str | None = None
    runtime: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "root": str(self.root), "kinds": list(self.kinds), "markers": list(self.markers),
            "entrypoints": list(self.entrypoints), "suggested_command": list(self.suggested_command),
            "git": self.git,
            "package_manager": self.package_manager, "test_framework": self.test_framework,
            "build_system": self.build_system, "virtual_environment": self.virtual_environment,
            "runtime": self.runtime,
        }


class ProjectDetector:
    MARKERS = {
        "pyproject.toml": "python", "requirements.txt": "python", "setup.py": "python",
        "package.json": "node", "vite.config.js": "vite", "vite.config.ts": "vite",
        "Cargo.toml": "rust", "CMakeLists.txt": "cmake", "go.mod": "go",
        "index.html": "web", "composer.json": "php", "pom.xml": "java",
        "build.gradle": "java", "build.gradle.kts": "java", "pubspec.yaml": "dart-flutter",
        "Makefile": "native", "tsconfig.json": "typescript",
    }

    def detect(self, path: str | Path) -> ProjectInfo:
        selected = Path(path).expanduser().resolve()
        if selected.is_file():
            selected = selected.parent
        if not selected.is_dir():
            raise FileNotFoundError("project_folder_not_found")
        root = self._find_root(selected)
        markers: list[str] = []
        kinds: list[str] = []
        for marker, kind in self.MARKERS.items():
            if (root / marker).exists():
                markers.append(marker)
                if kind not in kinds:
                    kinds.append(kind)
        solutions = sorted(root.glob("*.sln"))
        projects = sorted(root.glob("*.csproj"))
        if solutions or projects:
            markers.extend(item.name for item in (solutions + projects)[:20])
            kinds.append("dotnet")
        if list(root.glob("*.c")) or list(root.glob("*.h")):
            kinds.append("c")
        if list(root.glob("*.cpp")) or list(root.glob("*.cc")) or list(root.glob("*.hpp")):
            kinds.append("cpp")
        entrypoints: list[str] = []
        for name in ("app.py", "main.py", "manage.py", "index.html", "index.js", "server.js", "src/main.py"):
            if (root / name).is_file():
                entrypoints.append(name)
        command = self._suggested_command(root, kinds, entrypoints)
        if not kinds and not (root / ".git").exists():
            raise ValueError("project_markers_not_found")
        package_manager = self._package_manager(root, kinds)
        test_framework = self._test_framework(root, kinds)
        build_system = self._build_system(root, kinds)
        virtual_environment = next(
            (str(candidate.resolve()) for candidate in (root / ".venv", root / "venv") if candidate.is_dir()),
            None,
        )
        runtime = sys.executable if "python" in kinds else shutil.which("node") if "node" in kinds else None
        return ProjectInfo(
            root, tuple(kinds), tuple(markers), tuple(entrypoints), tuple(command),
            (root / ".git").exists(), package_manager, test_framework, build_system,
            virtual_environment, runtime,
        )

    @staticmethod
    def _package_manager(root: Path, kinds: list[str]) -> str | None:
        if "python" in kinds:
            if (root / "uv.lock").is_file():
                return "uv"
            if (root / "poetry.lock").is_file():
                return "poetry"
            return "pip"
        for marker, manager in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                                ("package-lock.json", "npm"), ("package.json", "npm")):
            if (root / marker).is_file():
                return manager
        if "rust" in kinds:
            return "cargo"
        if "go" in kinds:
            return "go"
        return None

    @staticmethod
    def _test_framework(root: Path, kinds: list[str]) -> str | None:
        if "python" in kinds:
            config = ""
            try:
                config = (root / "pyproject.toml").read_text(encoding="utf-8").casefold()
            except OSError:
                pass
            if "pytest" in config or (root / "pytest.ini").is_file() or (root / "tests").is_dir():
                return "pytest"
            return "unittest"
        if "node" in kinds:
            try:
                scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
                if "test" in scripts:
                    return "npm-test"
            except (OSError, ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _build_system(root: Path, kinds: list[str]) -> str | None:
        if (root / "pyproject.toml").is_file():
            return "pyproject"
        if "vite" in kinds:
            return "vite"
        if "node" in kinds:
            return "npm-scripts"
        if "dotnet" in kinds:
            return "msbuild"
        if "cmake" in kinds:
            return "cmake"
        if "rust" in kinds:
            return "cargo"
        if "go" in kinds:
            return "go"
        return None

    def _find_root(self, selected: Path) -> Path:
        fallback: Path | None = None
        current = selected
        for _ in range(12):
            if (current / ".git").exists():
                return current
            if any((current / marker).exists() for marker in self.MARKERS) or list(current.glob("*.sln")) or list(current.glob("*.csproj")):
                fallback = fallback or current
            if current.parent == current:
                break
            current = current.parent
        return fallback or selected

    @staticmethod
    def _suggested_command(root: Path, kinds: list[str], entrypoints: list[str]) -> list[str]:
        if "python" in kinds and entrypoints:
            return [sys.executable, entrypoints[0]]
        if "node" in kinds:
            try:
                package = json.loads((root / "package.json").read_text(encoding="utf-8"))
                scripts = package.get("scripts", {})
                script = "start" if "start" in scripts else "dev" if "dev" in scripts else "test" if "test" in scripts else ""
                npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
                if script:
                    return [npm, "run", script]
            except (OSError, ValueError, TypeError):
                pass
        if "dotnet" in kinds:
            return [shutil.which("dotnet") or "dotnet", "run"]
        if "java" in kinds:
            if (root / "pom.xml").is_file():
                return [shutil.which("mvn") or "mvn", "test"]
            if (root / "gradlew.bat").is_file():
                return [str(root / "gradlew.bat"), "test"]
        if "php" in kinds:
            return [shutil.which("php") or "php", "-S", "127.0.0.1:8000"]
        if "dart-flutter" in kinds:
            return [shutil.which("flutter") or shutil.which("dart") or "flutter", "test"]
        if "rust" in kinds:
            return [shutil.which("cargo") or "cargo", "run"]
        if "go" in kinds:
            return [shutil.which("go") or "go", "run", "."]
        return []
