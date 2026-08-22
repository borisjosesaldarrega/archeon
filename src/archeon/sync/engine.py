"""Deterministic, network-independent conflict resolution for settings sync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


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
