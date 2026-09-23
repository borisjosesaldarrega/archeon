"""Future cloud schemas only; no backend, client or background worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol


class CloudCapability(StrEnum):
    SETTINGS_SYNC = "settings.sync"
    TASK_HANDOFF = "tasks.handoff"
    ARTIFACT_SYNC = "artifacts.sync"
    DEVICE_PRESENCE = "devices.presence"


@dataclass(frozen=True, slots=True)
class CloudRequest:
    capability: CloudCapability
    identity_id: str
    payload: dict[str, Any]
    consent_token: str
    schema_version: int = 1

    def validate(self, *, authenticated_identity: str | None) -> None:
        if not authenticated_identity or authenticated_identity != self.identity_id:
            raise PermissionError("authenticated_cloud_identity_required")
        if not self.consent_token:
            raise PermissionError("explicit_cloud_consent_required")
        if self.schema_version != 1:
            raise ValueError("unsupported_cloud_schema")

    def public(self) -> dict[str, Any]:
        value = asdict(self); value["capability"] = self.capability.value; value["consent_token"] = "<redacted>"
        return value


@dataclass(frozen=True, slots=True)
class CloudResponse:
    request_id: str
    accepted: bool
    state: str
    evidence: dict[str, Any]


class FutureCloudProvider(Protocol):
    def execute(self, request: CloudRequest) -> CloudResponse: ...


class UnconfiguredCloudProvider:
    """Production-safe placeholder that never pretends a backend exists."""
    def execute(self, request: CloudRequest) -> CloudResponse:
        raise RuntimeError("future_cloud_backend_not_implemented")
