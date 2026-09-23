"""Security contracts shared by the desktop and future mobile clients."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping


class RemoteAction(StrEnum):
    SHUTDOWN = "system.shutdown"
    LAUNCH = "launcher.open"
    MEDIA_PLAY = "media.play"
    MEDIA_PAUSE = "media.pause"
    MEDIA_RESUME = "media.resume"
    MEDIA_STOP = "media.stop"


class CommandState(StrEnum):
    QUEUED = "queued"
    ACKNOWLEDGED = "acknowledged"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


HIGH_RISK_ACTIONS = frozenset({RemoteAction.SHUTDOWN})
SAFE_PREVIEW_MIME_TYPES = frozenset({
    "application/pdf", "image/gif", "image/jpeg", "image/png", "image/webp",
    "text/csv", "text/markdown", "text/plain",
})


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class RemoteCommand:
    id: str
    user_id: str
    source_device_id: str
    target_device_id: str
    action: RemoteAction
    arguments: Mapping[str, Any]
    risk: str
    idempotency_key: str
    nonce: str
    expires_at: str
    signature: str = ""
    confirmation_token_hash: str | None = None

    def signing_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["action"] = self.action.value
        value.pop("signature", None)
        return value

    def sign(self, pairing_secret: bytes) -> RemoteCommand:
        if len(pairing_secret) < 32:
            raise ValueError("pairing_secret_too_short")
        signature = base64.urlsafe_b64encode(
            hmac.new(pairing_secret, _canonical(self.signing_payload()), hashlib.sha256).digest()
        ).decode().rstrip("=")
        return RemoteCommand(**{**asdict(self), "signature": signature})

    def verify(self, pairing_secret: bytes) -> bool:
        if not self.signature or len(pairing_secret) < 32:
            return False
        expected = self.sign(pairing_secret).signature
        return hmac.compare_digest(expected, self.signature)

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        return expiry <= current

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> RemoteCommand:
        return cls(
            id=str(row["id"]), user_id=str(row["user_id"]),
            source_device_id=str(row["source_device_id"]),
            target_device_id=str(row["target_device_id"]),
            action=RemoteAction(str(row["action"])),
            arguments=dict(row.get("arguments") or {}), risk=str(row["risk"]),
            idempotency_key=str(row["idempotency_key"]), nonce=str(row["nonce"]),
            expires_at=str(row["expires_at"]), signature=str(row.get("signature") or ""),
            confirmation_token_hash=row.get("confirmation_token_hash"),
        )


@dataclass(frozen=True, slots=True)
class RemoteControlPolicy:
    local_device_id: str
    paired_source_ids: frozenset[str]
    remote_control_enabled: bool = False
    power_commands_enabled: bool = False

    def authorize(
        self,
        command: RemoteCommand,
        pairing_secret: bytes | None,
        *,
        confirmation_token: str | None = None,
        seen_idempotency_keys: set[str] | None = None,
        now: datetime | None = None,
    ) -> None:
        if command.target_device_id != self.local_device_id:
            raise PermissionError("remote_target_mismatch")
        if not self.remote_control_enabled:
            raise PermissionError("remote_control_disabled")
        if command.source_device_id not in self.paired_source_ids:
            raise PermissionError("remote_source_not_paired")
        if command.expired(now):
            raise PermissionError("remote_command_expired")
        if seen_idempotency_keys is not None and command.idempotency_key in seen_idempotency_keys:
            raise PermissionError("remote_command_replay")
        if not pairing_secret or not command.verify(pairing_secret):
            raise PermissionError("remote_signature_invalid")
        if command.action in HIGH_RISK_ACTIONS:
            if not self.power_commands_enabled:
                raise PermissionError("remote_power_commands_disabled")
            if not confirmation_token or not command.confirmation_token_hash:
                raise PermissionError("remote_confirmation_required")
            candidate = hashlib.sha256(confirmation_token.encode()).hexdigest()
            if not hmac.compare_digest(candidate, command.confirmation_token_hash):
                raise PermissionError("remote_confirmation_invalid")


def can_preview(mime_type: str) -> bool:
    return mime_type.strip().lower() in SAFE_PREVIEW_MIME_TYPES
