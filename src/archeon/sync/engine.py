"""Deterministic, network-independent conflict resolution for settings sync."""

from __future__ import annotations

import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ConflictResolution(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    EQUAL = "equal"


@dataclass(frozen=True, slots=True)
class SettingsEnvelope:
    version: int
    updated_at: str | None
    settings: Mapping[str, Any]


class SettingsSyncEngine:
    """Select the newest valid envelope; performs no polling or background work."""

    @staticmethod
    def resolve(local: SettingsEnvelope, remote: SettingsEnvelope) -> ConflictResolution:
        if local.version > remote.version:
            return ConflictResolution.LOCAL
        if remote.version > local.version:
            return ConflictResolution.REMOTE
        local_time = SettingsSyncEngine._timestamp(local.updated_at)
        remote_time = SettingsSyncEngine._timestamp(remote.updated_at)
        if local_time > remote_time:
            return ConflictResolution.LOCAL
        if remote_time > local_time:
            return ConflictResolution.REMOTE
        return ConflictResolution.EQUAL

    @staticmethod
    def _timestamp(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return 0.0


class CloudSyncOfflineError(RuntimeError):
    pass


class SupabaseSettingsSync:
    """On-demand PostgREST sync with an atomic offline queue and no worker thread."""

    def __init__(self, url: str, publishable_key: str, data_dir: Path, *, timeout: float = 8.0) -> None:
        self._url = url.rstrip("/")
        self._key = publishable_key
        self.configured = self._url.startswith("https://") and bool(self._key.strip())
        self._timeout = timeout
        self._queue_path = data_dir / "sync-pending.json"
        self._device_path = data_dir / "device-id.json"
        self.device_id = self._load_device_id()

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as temporary:
            json.dump(value, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
            pending = Path(temporary.name)
        os.replace(pending, path)

    def _load_device_id(self) -> str:
        try:
            value = json.loads(self._device_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("device_id"), str):
                return value["device_id"][:128]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        value = str(uuid.uuid4())
        self._atomic_json(self._device_path, {"device_id": value})
        return value

    def _request(
        self,
        method: str,
        resource: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
        *,
        prefer: str = "",
    ) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        request = Request(f"{self._url}/rest/v1/{resource}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode())
            except (UnicodeError, ValueError, json.JSONDecodeError):
                detail = {}
            raise ValueError(str(detail.get("code") or detail.get("message") or f"sync_http_{error.code}")) from None
        except (URLError, TimeoutError, OSError) as error:
            raise CloudSyncOfflineError("sync_offline") from error
        return json.loads(raw.decode()) if raw else None

    @staticmethod
    def _envelope(row: dict[str, Any] | None) -> SettingsEnvelope | None:
        if not row:
            return None
        settings = row.get("settings")
        if not isinstance(settings, dict):
            return None
        return SettingsEnvelope(max(1, int(row.get("version", 1))), row.get("updated_at"), settings)

    @staticmethod
    def _dict(envelope: SettingsEnvelope) -> dict[str, Any]:
        return {"version": envelope.version, "updated_at": envelope.updated_at, "settings": dict(envelope.settings)}

    def _select(self, table: str, filters: dict[str, str], access_token: str) -> dict[str, Any] | None:
        query = urlencode({key: f"eq.{value}" for key, value in filters.items()})
        value = self._request("GET", f"{table}?select=settings,version,updated_at&{query}&limit=1", access_token)
        return value[0] if isinstance(value, list) and value else None

    def _upsert(self, table: str, row: dict[str, Any], access_token: str) -> None:
        resource = f"{table}?on_conflict=user_id%2Cdevice_id" if table == "device_settings" else table
        self._request(
            "POST", resource, access_token, row,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def _resolve_scope(
        self,
        table: str,
        keys: dict[str, str],
        local_value: dict[str, Any],
        access_token: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        local = SettingsEnvelope(
            max(1, int(local_value.get("version", 0))),
            local_value.get("updated_at") or datetime.now(UTC).isoformat(),
            local_value.get("settings", {}),
        )
        remote = self._envelope(self._select(table, keys, access_token))
        if remote is None or SettingsSyncEngine.resolve(local, remote) is ConflictResolution.LOCAL:
            row = {**keys, **(extra or {}), **self._dict(local)}
            self._upsert(table, row, access_token)
            return self._dict(local), "uploaded"
        if SettingsSyncEngine.resolve(local, remote) is ConflictResolution.REMOTE:
            return self._dict(remote), "downloaded"
        return self._dict(remote), "equal"

    def synchronize(
        self,
        user_id: str,
        access_token: str,
        account: dict[str, Any],
        device: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.configured:
            raise ValueError("sync_backend_not_configured")
        if not user_id or not access_token:
            raise ValueError("account_session_required")
        try:
            account_selected, account_action = self._resolve_scope(
                "account_settings", {"user_id": user_id}, account, access_token,
            )
            device_selected, device_action = self._resolve_scope(
                "device_settings", {"user_id": user_id, "device_id": self.device_id}, device,
                access_token, {"device_name": (platform.node() or "Windows device")[:120]},
            )
        except CloudSyncOfflineError:
            self._atomic_json(self._queue_path, {"user_id": user_id, "account": account, "device": device})
            return {"ok": True, "queued": True, "status": "offline_queued"}
        try:
            self._queue_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "ok": True,
            "queued": False,
            "status": "synchronized",
            "account": account_selected,
            "device": device_selected,
            "actions": {"account": account_action, "device": device_action},
        }
