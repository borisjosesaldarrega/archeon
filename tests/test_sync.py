from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from archeon.sync import CloudSyncOfflineError, SupabaseSettingsSync


class MemorySettingsSync(SupabaseSettingsSync):
    def __init__(self, data_dir: Path) -> None:
        super().__init__("https://example.supabase.co", "publishable", data_dir)
        self.rows: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}

    def _select(self, table: str, filters: dict[str, str], access_token: str) -> dict[str, Any] | None:
        return self.rows.get((table, tuple(sorted(filters.items()))))

    def _upsert(self, table: str, row: dict[str, Any], access_token: str) -> None:
        keys = {"user_id": str(row["user_id"])}
        if table == "device_settings":
            keys["device_id"] = str(row["device_id"])
        self.rows[(table, tuple(sorted(keys.items())))] = row


class OfflineSettingsSync(SupabaseSettingsSync):
    def _resolve_scope(self, *args, **kwargs):
        raise CloudSyncOfflineError("sync_offline")


class SyncTests(unittest.TestCase):
    def test_unconfigured_sync_is_not_misreported_as_an_offline_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sync = SupabaseSettingsSync("", "", Path(temporary))
            envelope = {"version": 1, "updated_at": None, "settings": {}}
            with self.assertRaisesRegex(ValueError, "sync_backend_not_configured"):
                sync.synchronize("user-1", "jwt", envelope, envelope)
            self.assertFalse((Path(temporary) / "sync-pending.json").exists())

    def test_upload_then_download_newer_account_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sync = MemorySettingsSync(Path(temporary))
            local = {"version": 2, "updated_at": "2026-08-21T10:00:00+00:00", "settings": {"theme": "dark"}}
            device = {"version": 2, "updated_at": "2026-08-21T10:00:00+00:00", "settings": {"mic": "local"}}
            first = sync.synchronize("user-1", "jwt", local, device)
            self.assertEqual(first["actions"], {"account": "uploaded", "device": "uploaded"})
            account_key = ("account_settings", (("user_id", "user-1"),))
            sync.rows[account_key].update({
                "version": 3,
                "updated_at": "2026-08-21T11:00:00+00:00",
                "settings": {"theme": "light"},
            })
            second = sync.synchronize("user-1", "jwt", local, device)
            self.assertEqual(second["actions"]["account"], "downloaded")
            self.assertEqual(second["account"]["settings"]["theme"], "light")

    def test_offline_sync_writes_atomic_pending_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sync = OfflineSettingsSync("https://example.supabase.co", "publishable", root)
            envelope = {"version": 1, "updated_at": None, "settings": {"theme": "dark"}}
            result = sync.synchronize("user-1", "jwt", envelope, envelope)
            self.assertTrue(result["queued"])
            pending = json.loads((root / "sync-pending.json").read_text(encoding="utf-8"))
            self.assertEqual(pending["user_id"], "user-1")
            self.assertEqual(pending["account"]["settings"]["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
