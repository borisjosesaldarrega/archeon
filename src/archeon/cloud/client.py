"""Small authenticated Supabase client for ARCHEON Cloud.

The client is deliberately on-demand: it creates no worker threads and never
uses a service-role key. Realtime subscriptions belong to the mobile/desktop
transport layer; these methods provide the same deterministic REST contract.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .models import RemoteCommand, can_preview


class CloudOfflineError(RuntimeError):
    pass


class ArcheonCloudClient:
    BUCKET = "archeon-cloud"
    MAX_FILE_BYTES = 100 * 1024 * 1024

    def __init__(self, url: str, publishable_key: str, *, timeout: float = 12.0) -> None:
        self._url = url.strip().rstrip("/")
        self._key = publishable_key.strip()
        self._timeout = timeout
        self.configured = self._url.startswith("https://") and bool(self._key)

    def _request(
        self,
        method: str,
        path: str,
        access_token: str,
        payload: Any = None,
        *,
        content_type: str = "application/json",
        prefer: str = "",
    ) -> Any:
        if not self.configured:
            raise ValueError("cloud_backend_not_configured")
        body = payload if isinstance(payload, bytes) else (
            None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        )
        headers = {"apikey": self._key, "Authorization": f"Bearer {access_token}"}
        if body is not None:
            headers["Content-Type"] = content_type
        if prefer:
            headers["Prefer"] = prefer
        request = Request(f"{self._url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                response_type = response.headers.get_content_type()
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode())
            except (UnicodeError, ValueError, json.JSONDecodeError):
                detail = {}
            raise ValueError(str(detail.get("code") or detail.get("message") or f"cloud_http_{error.code}")) from None
        except (URLError, TimeoutError, OSError) as error:
            raise CloudOfflineError("cloud_offline") from error
        if not raw:
            return None
        if response_type == "application/json":
            return json.loads(raw.decode())
        return raw

    def _rest(
        self, method: str, table: str, access_token: str, payload: Any = None, *,
        query: dict[str, str] | None = None, prefer: str = "return=representation",
    ) -> Any:
        suffix = f"?{urlencode(query or {})}" if query else ""
        return self._request(method, f"/rest/v1/{table}{suffix}", access_token, payload, prefer=prefer)

    def register_device(
        self, access_token: str, *, user_id: str, installation_id: str,
        display_name: str, platform: str, public_key: str, capabilities: list[str],
    ) -> dict[str, Any]:
        rows = self._rest(
            "POST", "archeon_devices", access_token,
            {
                "user_id": user_id, "installation_id": installation_id,
                "display_name": display_name[:120], "platform": platform,
                "public_key": public_key, "capabilities": sorted(set(capabilities)),
            },
            query={"on_conflict": "user_id,installation_id"},
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not isinstance(rows, list) or not rows:
            raise ValueError("device_registration_failed")
        return dict(rows[0])

    def list_devices(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        value = self._rest(
            "GET", "archeon_devices", access_token,
            query={
                "select": "id,display_name,platform,capabilities,remote_control_enabled,power_commands_enabled,file_access_enabled,paired_at,last_seen_at",
                "user_id": f"eq.{user_id}", "order": "last_seen_at.desc",
            }, prefer="",
        )
        return [dict(row) for row in value] if isinstance(value, list) else []

    def queue_command(self, access_token: str, command: RemoteCommand) -> dict[str, Any]:
        if not command.signature:
            raise ValueError("remote_command_unsigned")
        row = command.signing_payload() | {"signature": command.signature, "state": "queued"}
        rows = self._rest("POST", "archeon_remote_commands", access_token, row)
        if not isinstance(rows, list) or not rows:
            raise ValueError("remote_command_queue_failed")
        return dict(rows[0])

    def pending_commands(self, access_token: str, *, user_id: str, target_device_id: str) -> list[RemoteCommand]:
        value = self._rest(
            "GET", "archeon_remote_commands", access_token,
            query={
                "select": "id,user_id,source_device_id,target_device_id,action,arguments,risk,idempotency_key,nonce,expires_at,signature,confirmation_token_hash",
                "user_id": f"eq.{user_id}", "target_device_id": f"eq.{target_device_id}",
                "state": "eq.queued", "order": "created_at.asc", "limit": "20",
            }, prefer="",
        )
        return [RemoteCommand.from_row(row) for row in value] if isinstance(value, list) else []

    def set_command_state(
        self, access_token: str, command_id: str, state: str, *,
        error_code: str | None = None, result: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"state": state}
        if error_code:
            payload["error_code"] = error_code[:120]
        if result is not None:
            payload["result"] = result
        self._rest(
            "PATCH", "archeon_remote_commands", access_token, payload,
            query={"id": f"eq.{command_id}"}, prefer="return=minimal",
        )

    def create_conversation(self, access_token: str, user_id: str, title: str = "Nuevo chat") -> dict[str, Any]:
        rows = self._rest("POST", "archeon_conversations", access_token, {"user_id": user_id, "title": title.strip()[:120] or "Nuevo chat"})
        return dict(rows[0])

    def list_conversations(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        value = self._rest(
            "GET", "archeon_conversations", access_token,
            query={"select": "id,title,created_at,updated_at", "user_id": f"eq.{user_id}", "archived_at": "is.null", "order": "updated_at.desc"},
            prefer="",
        )
        return [dict(row) for row in value] if isinstance(value, list) else []

    def rename_conversation(
        self, access_token: str, *, user_id: str, conversation_id: str, title: str,
    ) -> dict[str, Any]:
        clean = title.strip()[:120]
        if not clean:
            raise ValueError("conversation_title_required")
        rows = self._rest(
            "PATCH", "archeon_conversations", access_token, {"title": clean, "updated_at": datetime.now(UTC).isoformat()},
            query={"id": f"eq.{conversation_id}", "user_id": f"eq.{user_id}"},
        )
        if not isinstance(rows, list) or not rows:
            raise ValueError("conversation_not_found")
        return dict(rows[0])

    def archive_conversation(self, access_token: str, *, user_id: str, conversation_id: str) -> None:
        self._rest(
            "PATCH", "archeon_conversations", access_token,
            {"archived_at": datetime.now(UTC).isoformat(), "updated_at": datetime.now(UTC).isoformat()},
            query={"id": f"eq.{conversation_id}", "user_id": f"eq.{user_id}"}, prefer="return=minimal",
        )

    def add_message(
        self, access_token: str, *, user_id: str, conversation_id: str,
        role: str, body: str, source_device_id: str | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        message = {
            "user_id": user_id, "conversation_id": conversation_id, "role": role,
            "body": body, "source_device_id": source_device_id,
            "client_message_id": client_message_id or str(uuid4()),
        }
        rows = self._rest("POST", "archeon_messages", access_token, message)
        return dict(rows[0])

    def list_messages(self, access_token: str, conversation_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        value = self._rest(
            "GET", "archeon_messages", access_token,
            query={"select": "id,role,body,source_device_id,created_at", "conversation_id": f"eq.{conversation_id}", "order": "created_at.asc", "limit": str(max(1, min(limit, 500)))},
            prefer="",
        )
        return [dict(row) for row in value] if isinstance(value, list) else []

    def upload_file(
        self, access_token: str, *, user_id: str, source: Path,
        uploader_device_id: str | None = None, conversation_id: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        path = source.expanduser().resolve(strict=True)
        size = path.stat().st_size
        if size > self.MAX_FILE_BYTES:
            raise ValueError("cloud_file_too_large")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        visible_name = Path(display_name or path.name).name.strip()
        if not visible_name or visible_name in {".", ".."}:
            raise ValueError("cloud_file_name_invalid")
        object_path = f"{user_id}/{uuid4()}/{visible_name}"
        self._request(
            "POST", f"/storage/v1/object/{self.BUCKET}/{quote(object_path, safe='/')}",
            access_token, data, content_type=mime_type,
        )
        rows = self._rest(
            "POST", "archeon_cloud_files", access_token,
            {
                "user_id": user_id, "uploader_device_id": uploader_device_id,
                "conversation_id": conversation_id, "storage_path": object_path,
                "display_name": visible_name, "mime_type": mime_type,
                "byte_size": size, "sha256": digest, "state": "available",
            },
        )
        result = dict(rows[0])
        result["preview_allowed"] = can_preview(mime_type)
        return result

    def list_files(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        value = self._rest(
            "GET", "archeon_cloud_files", access_token,
            query={
                "select": "id,display_name,mime_type,byte_size,sha256,state,conversation_id,uploader_device_id,created_at",
                "user_id": f"eq.{user_id}", "state": "neq.deleted", "order": "created_at.desc",
            }, prefer="",
        )
        return [dict(row) | {"preview_allowed": can_preview(str(row.get("mime_type", "")))} for row in value] if isinstance(value, list) else []

    def get_file(self, access_token: str, *, user_id: str, file_id: str) -> dict[str, Any]:
        value = self._rest(
            "GET", "archeon_cloud_files", access_token,
            query={
                "select": "id,display_name,mime_type,byte_size,sha256,state,storage_path,conversation_id,created_at",
                "id": f"eq.{file_id}", "user_id": f"eq.{user_id}",
                "state": "eq.available", "limit": "1",
            }, prefer="",
        )
        if not isinstance(value, list) or not value:
            raise ValueError("cloud_file_not_found")
        row = dict(value[0])
        row["preview_allowed"] = can_preview(str(row.get("mime_type", "")))
        return row

    def download_file(self, access_token: str, storage_path: str) -> bytes:
        value = self._request(
            "GET", f"/storage/v1/object/authenticated/{self.BUCKET}/{quote(storage_path, safe='/')}",
            access_token,
        )
        if not isinstance(value, bytes):
            raise ValueError("cloud_file_download_failed")
        return value

    def download_verified_file(
        self, access_token: str, *, storage_path: str, expected_sha256: str,
    ) -> bytes:
        value = self.download_file(access_token, storage_path)
        if hashlib.sha256(value).hexdigest() != expected_sha256:
            raise ValueError("cloud_file_integrity_failed")
        return value

    def delete_file(self, access_token: str, file_id: str, storage_path: str) -> None:
        self._request(
            "DELETE", f"/storage/v1/object/{self.BUCKET}", access_token,
            {"prefixes": [storage_path]},
        )
        self._rest(
            "PATCH", "archeon_cloud_files", access_token, {"state": "deleted"},
            query={"id": f"eq.{file_id}"}, prefer="return=minimal",
        )
