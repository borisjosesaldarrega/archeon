"""Extensible, lazy programming-language and toolchain intelligence.

This module is deliberately metadata-driven.  Importing it does not probe the
machine or start a language server; toolchains are resolved only when a caller
asks for one.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    id: str
    display_name: str
    extensions: tuple[str, ...]
    aliases: tuple[str, ...]
    toolchains: tuple[str, ...]
    conventions: tuple[str, ...]
    validation_strategy: tuple[str, ...]
    build_strategy: tuple[str, ...]
    security_pitfalls: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _profile(
    identifier: str, name: str, extensions: str, aliases: str, tools: str,
    conventions: str, validation: str, build: str, pitfalls: str,
) -> LanguageProfile:
    split = lambda value: tuple(item.strip() for item in value.split("|") if item.strip())
    return LanguageProfile(identifier, name, split(extensions), split(aliases), split(tools),
                           split(conventions), split(validation), split(build), split(pitfalls))


BUILTIN_PROFILES = (
    _profile("python", "Python", ".py", "python|py", "python|pip",
             "pyproject.toml|src layout for larger packages|pytest", "compileall|pytest", "python -m", "unsafe eval|shell injection|untrusted pickle"),
    _profile("javascript", "JavaScript", ".js|.mjs|.cjs", "javascript|js|node", "node|npm|pnpm|yarn",
             "preserve ESM or CommonJS|package.json", "node --check|project tests", "npm scripts", "prototype pollution|DOM injection|unsafe child_process"),
    _profile("typescript", "TypeScript", ".ts|.tsx", "typescript|ts", "node|npm|tsc",
             "tsconfig.json|typed imports", "tsc --noEmit|project tests", "tsc|npm scripts", "any leakage|unsafe assertions|DOM injection"),
    _profile("html", "HTML5", ".html|.htm", "html|html5", "", "semantic HTML|accessible labels|keyboard support", "parse|resource paths|browser smoke", "none", "XSS|unsafe inline HTML"),
    _profile("css", "CSS3", ".css", "css|css3", "", "custom properties|responsive|reduced motion", "syntax|responsive smoke", "none", "unbounded animation|contrast failures"),
    _profile("sql", "SQL", ".sql", "sql|postgresql|postgres|mysql|mariadb|sqlite|sql server|tsql", "psql|mysql|sqlite3|sqlcmd",
             "dialect-specific migrations|transactions", "parse in selected dialect|migration test", "database migration tool", "destructive statements|SQL injection|missing constraints"),
    _profile("c", "C", ".c|.h", "lenguaje c|c language", "gcc|clang|cmake", "headers|explicit ownership|CMake when useful", "compile with warnings|tests", "compiler|cmake", "buffer overflow|use-after-free|integer overflow"),
    _profile("cpp", "C++", ".cpp|.cc|.cxx|.hpp|.hh", "c++|cpp|cplusplus", "g++|clang++|cmake", "RAII|STL|namespaces|CMake", "compile with warnings|tests", "compiler|cmake", "undefined behavior|raw ownership|iterator invalidation"),
    _profile("csharp", "C#", ".cs|.csproj|.sln", "c#|csharp|dotnet|.net", "dotnet", ".NET project|namespaces|async-await", "dotnet build|dotnet test", "dotnet", "unsafe deserialization|secret configuration"),
    _profile("java", "Java", ".java|pom.xml|build.gradle", "java|jdk|maven|gradle", "java|javac|mvn|gradle", "packages|Maven or Gradle only when useful", "javac|mvn test|gradle test", "javac|maven|gradle", "unsafe deserialization|command injection"),
    _profile("php", "PHP", ".php|composer.json", "php|composer", "php|composer", "Composer autoload when useful", "php -l|project tests", "php|composer", "file inclusion|SQL injection|output escaping"),
    _profile("powershell", "PowerShell", ".ps1|.psm1", "powershell|pwsh|ps1", "pwsh|powershell", "literal paths|approved verbs|error handling", "parser|Pester when present", "PowerShell", "unsafe interpolation|broad destructive paths"),
    _profile("bash", "Bash / Shell", ".sh|.bash", "bash|shell|sh", "bash", "portable shebang|strict quoting", "bash -n|shellcheck when present", "bash", "word splitting|glob expansion|unsafe rm"),
    _profile("dart", "Dart", ".dart|pubspec.yaml", "dart", "dart", "pubspec|lib layout", "dart analyze|dart test", "dart", "unsafe URLs|unvalidated platform channels"),
    _profile("flutter", "Flutter", ".dart|pubspec.yaml", "flutter", "flutter|dart", "lib widgets screens services|registered assets", "flutter analyze|flutter test", "flutter build", "unsafe storage|unregistered assets"),
    _profile("json", "JSON", ".json", "json", "python|node", "valid UTF-8|documented schema", "strict parse", "none", "secret leakage|prototype keys"),
    _profile("yaml", "YAML", ".yaml|.yml", "yaml|yml", "python", "explicit structure|safe loader", "safe parse", "none", "unsafe tags|secret leakage"),
    _profile("xml", "XML", ".xml", "xml", "python", "namespaces|schema when supplied", "secure parse|schema when supplied", "none", "XXE|entity expansion"),
    _profile("markdown", "Markdown", ".md|.markdown", "markdown|md", "", "readable hierarchy|relative links", "link and asset paths", "none", "unsafe embedded HTML|broken links"),
)


class ProgrammingLanguageRouter:
    """Recognise languages independently from project type."""

    def __init__(self, profiles: tuple[LanguageProfile, ...] = BUILTIN_PROFILES) -> None:
        self._profiles = {profile.id: profile for profile in profiles}

    def register(self, profile: LanguageProfile) -> None:
        self._profiles[profile.id] = profile

    def route(self, request: str) -> tuple[LanguageProfile, ...]:
        normalized = f" {str(request).casefold()} "
        matches: list[LanguageProfile] = []
        # C++ and C# must be resolved before the standalone C token.
        ordered = sorted(self._profiles.values(), key=lambda item: max(map(len, item.aliases), default=0), reverse=True)
        consumed: list[tuple[int, int]] = []
        for profile in ordered:
            found = False
            for alias in sorted(profile.aliases, key=len, reverse=True):
                pattern = rf"(?<![\w]){re.escape(alias)}(?![\w])"
                match = re.search(pattern, normalized)
                if match and not any(start <= match.start() < end for start, end in consumed):
                    found = True; consumed.append(match.span()); break
            if found: matches.append(profile)
        return tuple(matches)

    def profiles(self) -> tuple[LanguageProfile, ...]:
        return tuple(self._profiles.values())


@dataclass(frozen=True, slots=True)
class ProjectTypeResolution:
    project_type: str
    framework: str | None
    runtime: str | None


class ProjectTypeResolver:
    def resolve(self, request: str) -> ProjectTypeResolution:
        value = str(request).casefold()
        framework = next((name for name in ("react", "vue", "angular", "vite", "express", "fastapi", "flask", "django", "spring", "flutter", "electron") if re.search(rf"\b{re.escape(name)}\b", value)), None)
        project_type = (
            "full-stack" if re.search(r"\bfull[ -]?stack\b|frontend.+backend|backend.+frontend", value)
            else "api" if re.search(r"\bapi\b|backend|servidor", value)
            else "cli" if re.search(r"\bcli\b|l[ií]nea de comandos|terminal", value)
            else "library" if re.search(r"\blibrar(?:y|y)|biblioteca", value)
            else "mobile" if re.search(r"\bflutter\b|m[oó]vil|mobile", value)
            else "frontend" if re.search(r"\bp[aá]gina|web|frontend|html", value)
            else "application"
        )
        runtime = "browser" if project_type == "frontend" else "node" if re.search(r"\bnode|express|electron\b", value) else "python" if re.search(r"\bpython|fastapi|flask|django\b", value) else None
        return ProjectTypeResolution(project_type, framework, runtime)


class ToolchainDetector:
    """Resolve executables lazily and cache short version probes."""

    COMMANDS = {
        "python": ("python", "--version"), "pip": ("pip", "--version"),
        "node": ("node", "--version"), "npm": ("npm", "--version"),
        "pnpm": ("pnpm", "--version"), "yarn": ("yarn", "--version"),
        "tsc": ("tsc", "--version"), "gcc": ("gcc", "--version"),
        "g++": ("g++", "--version"), "clang": ("clang", "--version"),
        "clang++": ("clang++", "--version"), "cmake": ("cmake", "--version"),
        "dotnet": ("dotnet", "--version"), "java": ("java", "-version"),
        "javac": ("javac", "-version"), "mvn": ("mvn", "--version"),
        "gradle": ("gradle", "--version"), "php": ("php", "--version"),
        "composer": ("composer", "--version"), "dart": ("dart", "--version"),
        "flutter": ("flutter", "--version"), "powershell": ("powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"),
        "pwsh": ("pwsh", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"),
        "bash": ("bash", "--version"), "git": ("git", "--version"),
        "psql": ("psql", "--version"), "mysql": ("mysql", "--version"),
        "sqlite3": ("sqlite3", "--version"), "sqlcmd": ("sqlcmd", "-?"),
    }

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds; self._cache: dict[str, tuple[float, dict[str, Any]]] = {}; self._lock = RLock()

    def detect(self, name: str, *, include_version: bool = True) -> dict[str, Any]:
        key = str(name).casefold().strip()
        if key not in self.COMMANDS: raise ValueError("unsupported_toolchain")
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= self.ttl_seconds and (include_version is False or cached[1].get("version_checked")):
                return dict(cached[1])
        executable = shutil.which(self.COMMANDS[key][0])
        result: dict[str, Any] = {"name": key, "available": bool(executable), "path": executable, "version": None, "version_checked": False}
        if executable and include_version:
            argv = (executable,) + self.COMMANDS[key][1:]
            try:
                completed = subprocess.run(argv, capture_output=True, text=True, timeout=4, check=False, shell=False)
                output = (completed.stdout or completed.stderr).strip().splitlines()
                result.update(version=(output[0][:300] if output else None), version_checked=True, exit_code=completed.returncode)
            except (OSError, subprocess.TimeoutExpired):
                result.update(version_checked=True, error="version_probe_failed")
        with self._lock: self._cache[key] = (now, dict(result))
        return result

    def detect_many(self, names: tuple[str, ...], *, include_version: bool = False) -> list[dict[str, Any]]:
        return [self.detect(name, include_version=include_version) for name in names]
