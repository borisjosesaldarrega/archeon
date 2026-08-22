"""Offline-first settings synchronization primitives."""

from .engine import ConflictResolution, SettingsEnvelope, SettingsSyncEngine

__all__ = ["ConflictResolution", "SettingsEnvelope", "SettingsSyncEngine"]
