"""Manifest-first, signed and process-isolated future extension contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Callable

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent

_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}(?:[-+][a-z0-9.-]+)?$", re.I)
_ENTRYPOINT = re.compile(
    r"^(?P<module>[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*):"
    r"(?P<attribute>[a-zA-Z_][a-zA-Z0-9_]*)$"
)
SignatureVerifier = Callable[[bytes, str, str], bool]
PermissionAuthorizer = Callable[[tuple[str, ...]], bool]
KNOWN_PERMISSIONS = frozenset({
    "filesystem.read", "filesystem.write", "network.access", "desktop.observe",
    "desktop.control", "browser.control", "microphone.capture", "audio.playback",
    "clipboard.read", "clipboard.write", "terminal.execute",
})


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    version: str
    entrypoint: str
    enabled: bool = False
    name: str = ""
    publisher: str = ""
    min_archeon_version: str = "10.0.0"
    capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    signature: str = ""
    sha256: str = ""
    signature_verified: bool = False
    directory: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id, "name": self.name, "version": self.version,
            "publisher": self.publisher, "min_archeon_version": self.min_archeon_version,
            "capabilities": list(self.capabilities), "permissions": list(self.permissions),
            "entrypoint": self.entrypoint, "dependencies": list(self.dependencies),
            "signature_present": bool(self.signature), "sha256": self.sha256,
            "signature_verified": self.signature_verified, "enabled": self.enabled,
            "isolation": "separate_process",
        }


class PluginManager(ManagedComponent):
    def __init__(
        self, events: EventBus, directory: Path, *, signature_verifier: SignatureVerifier | None = None,
        permission_authorizer: PermissionAuthorizer | None = None, archeon_version: str = "10.0.0",
    ) -> None:
        super().__init__("plugins")
        self._events = events; self._directory = directory; self._signature_verifier = signature_verifier
        self._permission_authorizer = permission_authorizer
        self._archeon_version = archeon_version
        self._manifests: dict[str, PluginManifest] = {}; self._active: dict[str, subprocess.Popen[str]] = {}
        self._lock = RLock()
        self._runtime_directory = self._directory / ".runtime"

    @property
    def loaded_count(self) -> int:
        return len(self._active)

    @property
    def signature_verifier_configured(self) -> bool:
        return bool(
            self._signature_verifier is not None
            and getattr(self._signature_verifier, "configured", True)
        )

    @staticmethod
    def _permissions_valid(value: Any) -> bool:
        return bool(
            isinstance(value, list)
            and all(isinstance(item, str) and item in KNOWN_PERMISSIONS for item in value)
            and len(value) == len(set(value))
        )

    def scan(self) -> tuple[PluginManifest, ...]:
        """Read JSON only. Extension code is never imported in ARCHEON's process."""
        discovered: dict[str, PluginManifest] = {}
        if not self._directory.exists(): return ()
        for path in sorted(self._directory.glob("*/plugin.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8")); plugin_id = str(data.get("id", "")); entrypoint = str(data.get("entrypoint", ""))
                if (
                    not _ID.fullmatch(plugin_id) or not _ENTRYPOINT.fullmatch(entrypoint)
                    or not self._permissions_valid(data.get("permissions", []))
                ): continue
                digest = str(data.get("payload_sha256") or data.get("hash") or data.get("sha256") or "").casefold(); signature = str(data.get("signature", ""))
                payload_verified = bool(digest and digest == self._directory_payload_sha256(path.parent))
                verified = bool(
                    payload_verified and self._signature_verifier and signature
                    and self._signature_verifier(self._canonical_manifest(data), signature, str(data.get("publisher", "")))
                )
                discovered[plugin_id] = PluginManifest(
                    plugin_id, str(data.get("version", "0")), entrypoint, bool(data.get("enabled", False)),
                    str(data.get("name", plugin_id)), str(data.get("publisher", "")), str(data.get("min_archeon_version", "10.0.0")),
                    tuple(map(str, data.get("capabilities", []))), tuple(map(str, data.get("permissions", []))),
                    tuple(map(str, data.get("dependencies", []))), signature, digest, verified, str(path.parent.resolve()),
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError): continue
        with self._lock: self._manifests = discovered
        return tuple(discovered.values())

    def inspect_arx(self, package: str | Path) -> dict[str, Any]:
        source = Path(package).expanduser().resolve()
        if source.suffix.casefold() != ".arx" or not source.is_file(): raise ValueError("invalid_arx_package")
        with zipfile.ZipFile(source) as archive:
            if archive.testzip() is not None: raise ValueError("arx_integrity_failed")
            entries = archive.infolist()
            if len(entries) > 2048 or sum(item.file_size for item in entries) > 256 * 1024 * 1024:
                raise ValueError("arx_size_limit_exceeded")
            normalized_names = [PurePosixPath(item.filename).as_posix().casefold() for item in entries]
            if len(normalized_names) != len(set(normalized_names)):
                raise ValueError("arx_duplicate_path_rejected")
            for item in entries:
                name = item.filename
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts: raise ValueError("arx_path_traversal_rejected")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("arx_symlink_rejected")
            if "plugin.json" not in archive.namelist(): raise ValueError("arx_manifest_missing")
            data = json.loads(archive.read("plugin.json"))
            plugin_id = str(data.get("id", "")); version = str(data.get("version", ""))
            entrypoint = str(data.get("entrypoint", "")); publisher = str(data.get("publisher", ""))
            signature = str(data.get("signature", "")); declared = str(data.get("payload_sha256", "")).casefold()
            manifest_valid = bool(
                _ID.fullmatch(plugin_id) and _VERSION.fullmatch(version)
                and _ENTRYPOINT.fullmatch(entrypoint)
                and self._permissions_valid(data.get("permissions", []))
            )
            payload = hashlib.sha256()
            for item in sorted((entry for entry in entries if not entry.is_dir() and entry.filename != "plugin.json"), key=lambda entry: entry.filename):
                payload.update(item.filename.encode("utf-8")); payload.update(b"\0")
                payload.update(hashlib.sha256(archive.read(item)).digest())
            payload_sha256 = payload.hexdigest()
            payload_verified = bool(declared and declared == payload_sha256)
            signature_verified = bool(
                manifest_valid and self._signature_verifier and signature
                and self._signature_verifier(self._canonical_manifest(data), signature, publisher)
            )
            compatible = self._compatible(str(data.get("min_archeon_version", "10.0.0")))
        return {
            "path": str(source), "id": plugin_id, "version": version,
            "publisher": publisher, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "payload_sha256": payload_sha256, "declared_payload_sha256": declared,
            "manifest_valid": manifest_valid, "payload_verified": payload_verified,
            "signature_present": bool(signature), "signature_verified": signature_verified,
            "compatible": compatible,
            "installable": bool(manifest_valid and payload_verified and signature_verified and compatible),
            "reason": (
                "ready" if manifest_valid and payload_verified and signature_verified and compatible else
                "invalid_manifest" if not manifest_valid else "payload_hash_mismatch" if not payload_verified else
                "trusted_signature_verification_required" if not signature_verified else "incompatible_archeon_version"
            ),
        }

    def install(self, package: str | Path, *, allow_update: bool = False) -> PluginManifest:
        inspection = self.inspect_arx(package)
        if not inspection["installable"]:
            raise PermissionError(str(inspection["reason"]))
        plugin_id = str(inspection["id"]); target = (self._directory / plugin_id).resolve()
        if target.parent != self._directory.resolve():
            raise ValueError("plugin_target_outside_directory")
        existing = next((item for item in self.scan() if item.plugin_id == plugin_id), None)
        if existing and not allow_update:
            raise FileExistsError("plugin_already_installed")
        if existing and self._version_key(str(inspection["version"])) <= self._version_key(existing.version):
            raise ValueError("plugin_update_version_must_increase")
        if existing:
            self.deactivate(plugin_id)
        self._directory.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{plugin_id}-", dir=self._directory))
        backup = self._directory / f".{plugin_id}.previous"
        try:
            with zipfile.ZipFile(Path(package).expanduser().resolve()) as archive:
                archive.extractall(staging)
            if target.exists():
                if backup.exists(): shutil.rmtree(backup)
                target.replace(backup)
            staging.replace(target)
            if backup.exists(): shutil.rmtree(backup)
        except Exception:
            if target.exists() and backup.exists(): shutil.rmtree(target)
            if backup.exists(): backup.replace(target)
            raise
        finally:
            if staging.exists(): shutil.rmtree(staging)
        installed = next((item for item in self.scan() if item.plugin_id == plugin_id), None)
        if installed is None or not installed.signature_verified:
            raise RuntimeError("installed_plugin_verification_failed")
        self._events.publish("plugin.installed", {"id": plugin_id, "version": installed.version}, source="plugins")
        return installed

    def update(self, package: str | Path) -> PluginManifest:
        return self.install(package, allow_update=True)

    def enable(self, plugin_id: str) -> None:
        self._set_enabled(plugin_id, True)
        self.scan(); self.activate(plugin_id)

    def disable(self, plugin_id: str) -> None:
        self.deactivate(plugin_id); self._set_enabled(plugin_id, False); self.scan()

    def remove(self, plugin_id: str) -> bool:
        if not _ID.fullmatch(plugin_id): raise ValueError("invalid_plugin_id")
        self.deactivate(plugin_id)
        target = (self._directory / plugin_id).resolve()
        if target.parent != self._directory.resolve(): raise ValueError("plugin_target_outside_directory")
        if not target.exists(): return False
        shutil.rmtree(target); self.scan()
        self._events.publish("plugin.removed", {"id": plugin_id}, source="plugins")
        return True

    def _set_enabled(self, plugin_id: str, enabled: bool) -> None:
        manifest = self._manifests.get(plugin_id) or next((item for item in self.scan() if item.plugin_id == plugin_id), None)
        if manifest is None: raise KeyError(plugin_id)
        path = Path(manifest.directory) / "plugin.json"
        data = json.loads(path.read_text(encoding="utf-8")); data["enabled"] = bool(enabled)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        core = re.split(r"[-+]", version, maxsplit=1)[0]
        return tuple(int(item) for item in core.split("."))

    def _compatible(self, minimum: str) -> bool:
        if not _VERSION.fullmatch(minimum) or not _VERSION.fullmatch(self._archeon_version): return False
        current = self._version_key(self._archeon_version); required = self._version_key(minimum)
        width = max(len(current), len(required))
        return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))

    def activate(self, plugin_id: str) -> None:
        with self._lock:
            if plugin_id in self._active: return
            manifest = next((item for item in self.scan() if item.plugin_id == plugin_id), None)
            if manifest is None:
                raise KeyError(plugin_id)
            if not manifest.signature_verified: raise PermissionError("plugin_trusted_signature_required")
            if not self._compatible(manifest.min_archeon_version): raise RuntimeError("plugin_archeon_version_incompatible")
            if manifest.permissions and (
                self._permission_authorizer is None
                or not self._permission_authorizer(manifest.permissions)
            ):
                raise PermissionError("plugin_permissions_not_granted")
            self._runtime_directory.mkdir(parents=True, exist_ok=True)
            ready_path = self._runtime_directory / f"{plugin_id}-{time.time_ns()}.ready"
            ready_token = secrets.token_urlsafe(32)
            manifest_path = Path(manifest.directory) / "plugin.json"
            command = (
                [
                    sys.executable, "--plugin-host", str(manifest_path),
                    "--plugin-ready-file", str(ready_path), "--plugin-ready-token", ready_token,
                ]
                if getattr(sys, "frozen", False) else
                [
                    sys.executable, str(Path(__file__).with_name("host.py").resolve()), str(manifest_path),
                    "--ready-file", str(ready_path), "--ready-token", ready_token,
                ]
            )
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.Popen(
                command, cwd=manifest.directory, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                text=True, shell=False, env=environment,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            deadline = time.monotonic() + 10.0
            ready = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    ready = ready_path.read_text(encoding="ascii").strip() == ready_token
                except (FileNotFoundError, OSError, UnicodeError):
                    ready = False
                if ready:
                    break
                time.sleep(0.02)
            ready_path.unlink(missing_ok=True)
            if not ready:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=2)
                self._events.publish(
                    "plugin.failed", {"id": plugin_id, "error": "plugin_startup_not_verified"},
                    source="plugins",
                )
                raise RuntimeError("plugin_startup_not_verified")
            self._active[plugin_id] = process
            self._events.publish("plugin.started", {"id": plugin_id, "pid": process.pid, "isolation": "process"}, source="plugins")

    def deactivate(self, plugin_id: str) -> None:
        with self._lock: process = self._active.pop(plugin_id, None)
        if process is not None:
            try: process.communicate("stop\n", timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            self._events.publish("plugin.stopped", {"id": plugin_id}, source="plugins")

    @staticmethod
    def _canonical_manifest(data: dict[str, Any]) -> bytes:
        return json.dumps(
            {key: value for key, value in data.items() if key not in {"signature", "enabled"}},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _directory_payload_sha256(directory: Path) -> str:
        payload = hashlib.sha256()
        files = sorted(
            (item for item in directory.rglob("*") if item.is_file() and item.name != "plugin.json"),
            key=lambda item: item.relative_to(directory).as_posix(),
        )
        for item in files:
            payload.update(item.relative_to(directory).as_posix().encode("utf-8")); payload.update(b"\0")
            payload.update(hashlib.sha256(item.read_bytes()).digest())
        return payload.hexdigest()

    def _start(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        for manifest in self.scan():
            if not manifest.enabled:
                continue
            try:
                self.activate(manifest.plugin_id)
            except (KeyError, OSError, PermissionError, RuntimeError, ValueError) as error:
                self._events.publish(
                    "plugin.failed", {"id": manifest.plugin_id, "error": str(error)}, source="plugins",
                )
    def _stop(self) -> None:
        for plugin_id in tuple(reversed(self._active)): self.deactivate(plugin_id)
        self._manifests.clear()
        if self._runtime_directory.is_dir():
            for ready_file in self._runtime_directory.glob("*.ready"):
                ready_file.unlink(missing_ok=True)
            try: self._runtime_directory.rmdir()
            except OSError: pass
