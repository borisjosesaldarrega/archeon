"""Small update coordinator that cannot pretend an update backend exists."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    notes: str
    download_url: str
    sha256: str
    signature: str

    def public(self) -> dict[str, str]:
        value = asdict(self)
        value["download_url"] = "<configured>" if self.download_url else ""
        value["signature"] = "<present>" if self.signature else ""
        return value


class UpdateProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    def check(self, current_version: str) -> ReleaseInfo | None: ...

    def download(self, release: ReleaseInfo, destination: Path) -> Path: ...


class UnconfiguredUpdateProvider:
    name = "not_configured"
    configured = False

    def check(self, current_version: str) -> ReleaseInfo | None:
        raise RuntimeError("update_backend_not_configured")

    def download(self, release: ReleaseInfo, destination: Path) -> Path:
        raise RuntimeError("update_backend_not_configured")


class UpdateManager:
    """Coordinates release state; installation remains a verified restart contract."""

    def __init__(self, current_version: str, provider: UpdateProvider | None = None) -> None:
        self.current_version = current_version
        self.provider = provider or UnconfiguredUpdateProvider()
        self.available: ReleaseInfo | None = None
        self.download_state = "idle"
        self.verification_state = "not_started"
        self.install_state = "not_started"
        self.last_error: str | None = None

    def status(self) -> dict[str, object]:
        return {
            "current_version": self.current_version,
            "provider": self.provider.name,
            "configured": bool(self.provider.configured),
            "available_version": self.available.version if self.available else None,
            "release_notes": self.available.notes if self.available else None,
            "download_state": self.download_state,
            "verification_state": self.verification_state,
            "install_state": self.install_state,
            "restart_required": self.install_state == "ready_to_install",
            "last_error": self.last_error,
        }

    def check(self) -> dict[str, object]:
        if not self.provider.configured:
            self.last_error = "update_backend_not_configured"
            return {"ok": False, "error": self.last_error, "status": self.status()}
        try:
            self.available = self.provider.check(self.current_version)
            self.last_error = None
            return {"ok": True, "status": self.status()}
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            return {"ok": False, "error": "update_check_failed", "status": self.status()}

    def mark_verified_download(self, path: Path, *, sha256_verified: bool, signature_verified: bool) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        if not sha256_verified or not signature_verified:
            self.download_state = "rejected"
            self.verification_state = "failed"
            raise PermissionError("update_integrity_verification_failed")
        self.download_state = "downloaded"
        self.verification_state = "verified"
        self.install_state = "ready_to_install"
