from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
import time
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault
from archeon.auth.manager import Identity, ProviderSession
from archeon.ui.server import UI_ROOT


class ApplicationUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.application = ArcheonApplication(
            data_dir=data_dir,
            port=0,
            auth_provider=DevelopmentAuthProvider(data_dir / "development-auth.json"),
            auth_vault=MemorySessionVault(),
        )
        self.application.start()
        self.session_token = self.application.auth.guest().token

    def tearDown(self) -> None:
        self.application.stop()
        self.temp.cleanup()

    def request(self, path: str, *, body: dict | None = None, authorized: bool = True):
        headers = {}
        data = None
        if authorized:
            headers["X-Archeon-Token"] = self.application.ui_server.token
            headers["X-Archeon-Session"] = self.session_token
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.application.ui_server.url + path, headers=headers, data=data)
        return urllib.request.urlopen(request, timeout=2)

    def test_health_requires_runtime_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/health", authorized=False)
        self.assertEqual(caught.exception.code, 401)
        with self.request("/api/health") as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tools_loaded"], 0)

    def test_real_command_flows_through_orchestrator(self) -> None:
        with self.request("/api/command", body={"text": "estado del sistema"}) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["data"]["logical_cpu_count"], 0)
        self.assertEqual(self.application.tools.loaded_tool_count, 1)

    def test_commands_require_an_application_session(self) -> None:
        request = urllib.request.Request(
            self.application.ui_server.url + "/api/command",
            headers={"X-Archeon-Token": self.application.ui_server.token, "Content-Type": "application/json"},
            data=json.dumps({"text": "estado del sistema"}).encode(),
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 401)

    def test_window_action_is_persisted_and_published(self) -> None:
        subscription = self.application.events.subscribe("ui.window.*")
        with self.request("/api/action", body={"action": "window.ghost"}) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertTrue(self.application.configuration.config.ghost.enabled)
        self.assertEqual(subscription.get(timeout=0.2).type, "ui.window.ghost")
        subscription.close()

    def test_settings_actions_are_real_and_emit_changes(self) -> None:
        subscription = self.application.events.subscribe("settings.changed")
        with self.request("/api/action", body={"action": "settings.get"}) as response:
            current = json.load(response)
        self.assertFalse(current["settings"]["startup"]["startup_sound"])
        with self.request(
            "/api/action",
            body={"action": "settings.update", "changes": {"assistant": {"wake_name": "Nova"}}},
        ) as response:
            updated = json.load(response)
        self.assertEqual(updated["settings"]["assistant"]["wake_name"], "Nova")
        self.assertEqual(subscription.get(timeout=0.2).payload["sections"], ["assistant"])
        subscription.close()

    def test_sync_action_uses_authenticated_session_without_exposing_provider_token(self) -> None:
        account = self.application.auth._create(
            ProviderSession(
                Identity("11111111-1111-1111-1111-111111111111", "owner@example.test", "Owner"),
                "provider-jwt", "provider-refresh", int(time.time()) + 3600, True,
            ),
            "account",
        )
        self.session_token = account.token
        captured = {}

        class FakeSync:
            def synchronize(_self, user_id, access_token, account_value, device_value):
                captured.update(user_id=user_id, access_token=access_token)
                return {
                    "ok": True, "queued": False, "status": "synchronized",
                    "account": account_value, "device": device_value,
                    "actions": {"account": "uploaded", "device": "uploaded"},
                }

        self.application.settings_sync = FakeSync()
        with self.request("/api/action", body={"action": "sync.now", "_session_token": "spoofed"}) as response:
            result = json.load(response)
        self.assertTrue(result["ok"])
        self.assertEqual(captured["user_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(captured["access_token"], "provider-jwt")
        self.assertNotIn("provider-jwt", json.dumps(result))

    def test_ghost_transition_resumes_session_once_in_memory(self) -> None:
        with self.request("/api/action", body={"action": "window.ghost"}) as response:
            self.assertTrue(json.load(response)["ok"])
        with urllib.request.urlopen(self.application.ui_server.url + "/runtime-config.js", timeout=2) as response:
            first = response.read().decode("utf-8")
        with urllib.request.urlopen(self.application.ui_server.url + "/runtime-config.js", timeout=2) as response:
            second = response.read().decode("utf-8")
        self.assertIn(self.session_token, first)
        self.assertNotIn(self.session_token, second)

    def test_ui_uses_events_not_polling(self) -> None:
        javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("EventSource", javascript)
        self.assertNotIn("setInterval", javascript)
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<audio", html)
        self.assertTrue((UI_ROOT / "locales" / "es.json").is_file())
        self.assertTrue((UI_ROOT / "locales" / "en.json").is_file())
        for locale in ("es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi"):
            catalog = json.loads((UI_ROOT / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
            self.assertIn("settings.title", catalog)

    def test_ui_assets_cannot_mix_versions_from_browser_cache(self) -> None:
        with self.request("/app.js") as response:
            response.read()
            self.assertEqual(response.headers["Cache-Control"], "no-cache, must-revalidate")

    def test_music_events_are_real_actions(self) -> None:
        subscription = self.application.events.subscribe("music.volume.changed")
        with self.request("/api/action", body={"action": "media.volume", "volume": 0.35}) as response:
            self.assertTrue(json.load(response)["ok"])
        event = subscription.get(timeout=0.2)
        self.assertEqual(event.type, "music.volume.changed")
        self.assertEqual(event.payload["volume"], 0.35)
        subscription.close()

    def test_voice_configuration_is_validated_and_persisted(self) -> None:
        catalog = {
            "profiles": ["eco", "balanced", "performance"],
            "input_devices": [{"index": 28, "name": "Shared microphone"}],
            "tts_voices": [{"id": "voice-es", "name": "Spanish voice"}],
            "tts_outputs": [{"id": "output-1", "name": "Speakers"}],
            "status": self.application.voice.status(),
        }
        original_catalog = self.application.voice.catalog
        self.application.voice.catalog = lambda: catalog
        try:
            with self.request(
                "/api/action",
                body={
                    "action": "voice.configure",
                    "profile": "balanced",
                    "input_device_id": "28",
                    "tts_voice_id": "voice-es",
                    "tts_output_device_id": "output-1",
                    "tts_rate": 2,
                    "tts_volume": 72,
                    "barge_in": False,
                },
            ) as response:
                payload = json.load(response)
        finally:
            self.application.voice.catalog = original_catalog
        self.assertTrue(payload["ok"])
        config = json.loads((Path(self.temp.name) / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["voice"]["profile"], "balanced")
        self.assertEqual(config["audio"]["input_device_id"], "28")
        self.assertEqual(config["voice"]["tts_output_device_id"], "output-1")
        self.assertFalse(config["voice"]["barge_in"])

    def test_guest_session_is_local_and_logout_invalidates_it(self) -> None:
        with self.request("/api/auth/guest", body={}) as response:
            created = json.load(response)
        self.assertTrue(created["ok"])
        self.assertEqual(created["session"]["mode"], "guest")
        session_token = created["session_token"]
        request = urllib.request.Request(
            self.application.ui_server.url + "/api/session",
            headers={
                "X-Archeon-Token": self.application.ui_server.token,
                "X-Archeon-Session": session_token,
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertTrue(json.load(response)["ok"])

    def test_development_register_and_login_flow(self) -> None:
        account = {"email": "test@example.com", "password": "correct-horse", "display_name": "Test"}
        with self.request("/api/auth/register", body=account) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request(
            "/api/auth/login", body={"email": account["email"], "password": account["password"]}
        ) as response:
            logged_in = json.load(response)
        self.assertTrue(logged_in["ok"])
        self.assertEqual(logged_in["session"]["identity"]["display_name"], "Test")

    def test_server_stops_its_thread(self) -> None:
        self.assertTrue(self.application.ui_server.thread_alive)
        self.application.stop()
        self.assertFalse(self.application.ui_server.thread_alive)

    def test_personalization_video_supports_bounded_range_streaming(self) -> None:
        video = Path(self.temp.name) / "background.mp4"
        video.write_bytes(b"0123456789")
        self.application.configuration.update_settings(
            {"appearance": {"background_type": "video", "background_path": str(video)}}
        )
        request = urllib.request.Request(
            self.application.ui_server.url + "/personalization/background",
            headers={"X-Archeon-Token": self.application.ui_server.token, "Range": "bytes=2-5"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")


if __name__ == "__main__":
    unittest.main()
