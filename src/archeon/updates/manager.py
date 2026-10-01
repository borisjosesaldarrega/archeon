"""Small update coordinator that cannot pretend an update backend exists."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


class GitHubReleaseProvider:
    """Read official releases and require GitHub's SHA-256 asset digest."""

    name = "github_releases"
    configured = True

    def __init__(self, repository: str, *, timeout: float = 10.0) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid_github_repository")
        self.repository = repository
        self.timeout = timeout

    @staticmethod
    def _version_key(value: str) -> tuple[int, ...]:
        numbers = [int(item) for item in re.findall(r"\d+", value)]
        return tuple((numbers + [0, 0, 0, 0])[:4])

    def check(self, current_version: str) -> ReleaseInfo | None:
        request = Request(
            f"https://api.github.com/repos/{self.repository}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ARCHEON-Updater/10"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise RuntimeError(f"github_release_http_{error.code}") from None
        except (OSError, URLError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("github_release_unavailable") from error
        version = str(value.get("tag_name") or "").lstrip("vV")
        if not version or self._version_key(version) <= self._version_key(current_version):
            return None
        assets = value.get("assets") if isinstance(value.get("assets"), list) else []
        asset = next((item for item in assets if re.search(r"(?:instalar.*archeon|archeon.*setup).*\.exe$", str(item.get("name") or ""), re.I)), None)
        if not isinstance(asset, dict):
            return None
        digest = str(asset.get("digest") or "")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise RuntimeError("release_asset_digest_missing")
        url = str(asset.get("browser_download_url") or "")
        if not url.startswith(f"https://github.com/{self.repository}/releases/download/"):
            raise RuntimeError("release_asset_url_invalid")
        return ReleaseInfo(
            version=version, notes=str(value.get("body") or "Nueva versión de ARCHEON.")[:8000],
            download_url=url, sha256=digest.split(":", 1)[1].lower(),
            signature="github-release-asset-digest",
        )

    def download(self, release: ReleaseInfo, destination: Path) -> Path:
        target = destination.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_suffix(target.suffix + ".part")
        digest = hashlib.sha256()
        total = 0
        request = Request(release.download_url, headers={"User-Agent": "ARCHEON-Updater/10"})
        try:
            with urlopen(request, timeout=max(self.timeout, 30.0)) as response, pending.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 500 * 1024 * 1024:
                        raise ValueError("update_package_too_large")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != release.sha256:
                raise PermissionError("update_sha256_mismatch")
            pending.replace(target)
            return target
        except Exception:
            pending.unlink(missing_ok=True)
            raise


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
