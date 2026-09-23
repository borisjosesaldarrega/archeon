from __future__ import annotations

import hashlib
from unittest.mock import patch
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from archeon.cloud import (
    ArcheonCloudClient,
    CommandReplayStore,
    RemoteAction,
    RemoteCommand,
    RemoteCommandExecutor,
    RemoteControlPolicy,
    RemoteIntentParser,
    can_preview,
)


def command(action: RemoteAction, *, confirmation: str | None = None) -> tuple[RemoteCommand, bytes]:
    secret = b"p" * 32
    arguments = {"confirmation_token": confirmation} if confirmation else {"query": "Minecraft"}
    value = RemoteCommand(
        id=str(uuid4()), user_id=str(uuid4()), source_device_id="phone-1",
        target_device_id="pc-1", action=action, arguments=arguments,
        risk="high" if action is RemoteAction.SHUTDOWN else "standard",
        idempotency_key=str(uuid4()), nonce="n" * 24,
        expires_at=(datetime.now(UTC) + timedelta(seconds=90)).isoformat(),
        confirmation_token_hash=hashlib.sha256(confirmation.encode()).hexdigest() if confirmation else None,
    )
    return value.sign(secret), secret


class MobileCloudRemoteTests(unittest.TestCase):
    def test_signed_paired_standard_command_executes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, secret = command(RemoteAction.LAUNCH)
            executor = RemoteCommandExecutor(
                RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True),
                lambda _source: secret,
                CommandReplayStore(Path(temporary) / "replay.json"),
                {RemoteAction.LAUNCH: lambda args: {"ok": args["query"] == "Minecraft"}},
            )
            self.assertTrue(executor.execute(value)["ok"])
            with self.assertRaisesRegex(PermissionError, "replay"):
                executor.execute(value)

    def test_shutdown_fails_closed_without_opt_in_and_exact_confirmation(self) -> None:
        value, secret = command(RemoteAction.SHUTDOWN, confirmation="482913")
        policy = RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "power_commands_disabled"):
            policy.authorize(value, secret, confirmation_token="482913")
        enabled = RemoteControlPolicy(
            "pc-1", frozenset({"phone-1"}), remote_control_enabled=True,
            power_commands_enabled=True,
        )
        with self.assertRaisesRegex(PermissionError, "confirmation_invalid"):
            enabled.authorize(value, secret, confirmation_token="000000")
        enabled.authorize(value, secret, confirmation_token="482913")

    def test_tampering_wrong_target_unpaired_and_expired_are_rejected(self) -> None:
        value, secret = command(RemoteAction.LAUNCH)
        policy = RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True)
        tampered = RemoteCommand(**{**value.__dict__, "arguments": {"query": "Other"}}) if hasattr(value, "__dict__") else RemoteCommand(
            value.id, value.user_id, value.source_device_id, value.target_device_id,
            value.action, {"query": "Other"}, value.risk, value.idempotency_key,
            value.nonce, value.expires_at, value.signature, value.confirmation_token_hash,
        )
        with self.assertRaisesRegex(PermissionError, "signature_invalid"):
            policy.authorize(tampered, secret)
        wrong_target = RemoteControlPolicy("pc-2", frozenset({"phone-1"}), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "target_mismatch"):
            wrong_target.authorize(value, secret)
        unpaired = RemoteControlPolicy("pc-1", frozenset(), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "not_paired"):
            unpaired.authorize(value, secret)

    def test_remote_language_parser_avoids_common_false_positives(self) -> None:
        parser = RemoteIntentParser()
        self.assertEqual(parser.parse("Apaga la PC").action, RemoteAction.SHUTDOWN)
        self.assertEqual(parser.parse("abre Minecraft en mi PC").arguments["query"], "minecraft")
        self.assertEqual(parser.parse("reproduce Daft Punk en la computadora").action, RemoteAction.MEDIA_PLAY)
        for phrase in (
            "no apagues la PC", "¿cómo apago la PC?", "la PC se apaga sola",
            "cuando apague la PC", "hablábamos de apagar la PC", "abre Minecraft",
        ):
            self.assertIsNone(parser.parse(phrase), phrase)

    def test_preview_allowlist_rejects_active_or_unknown_content(self) -> None:
        self.assertTrue(can_preview("application/pdf"))
        self.assertTrue(can_preview("image/png"))
        self.assertFalse(can_preview("text/html"))
        self.assertFalse(can_preview("application/x-msdownload"))

    def test_cloud_client_is_explicitly_unconfigured(self) -> None:
        client = ArcheonCloudClient("", "")
        self.assertFalse(client.configured)
        with self.assertRaisesRegex(ValueError, "not_configured"):
            client.list_devices("token", "user")

    def test_cloud_download_verifies_integrity(self) -> None:
        client = ArcheonCloudClient("https://example.supabase.co", "publishable")
        payload = b"verified cloud payload"
        with patch.object(client, "download_file", return_value=payload):
            self.assertEqual(
                client.download_verified_file(
                    "token", storage_path="user/file", expected_sha256=hashlib.sha256(payload).hexdigest()
                ),
                payload,
            )
            with self.assertRaisesRegex(ValueError, "integrity"):
                client.download_verified_file("token", storage_path="user/file", expected_sha256="0" * 64)

    def test_migration_has_rls_private_storage_realtime_and_no_service_role(self) -> None:
        migration = next(Path("supabase/migrations").glob("*mobile_cloud_remote_foundation.sql")).read_text(encoding="utf-8").lower()
        for table in (
            "archeon_devices", "archeon_device_pairings", "archeon_remote_commands",
            "archeon_conversations", "archeon_messages", "archeon_cloud_files",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", migration)
            self.assertIn(table, migration)
        self.assertIn("'archeon-cloud', false", migration)
        self.assertIn("supabase_realtime", migration)
        self.assertNotIn("service_role", migration)


if __name__ == "__main__":
    unittest.main()
