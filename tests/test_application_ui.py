from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.ui.server import UI_ROOT


class ApplicationUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.application = ArcheonApplication(data_dir=Path(self.temp.name), port=0)
        self.application.start()

    def tearDown(self) -> None:
        self.application.stop()
        self.temp.cleanup()

    def request(self, path: str, *, body: dict | None = None, authorized: bool = True):
        headers = {}
        data = None
        if authorized:
            headers["X-Archeon-Token"] = self.application.ui_server.token
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

    def test_window_action_is_persisted_and_published(self) -> None:
        subscription = self.application.events.subscribe("ui.window.*")
        with self.request("/api/action", body={"action": "window.ghost"}) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertTrue(self.application.configuration.config.ghost.enabled)
        self.assertEqual(subscription.get(timeout=0.2).type, "ui.window.ghost")
        subscription.close()

    def test_ui_uses_events_not_polling(self) -> None:
        javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("EventSource", javascript)
        self.assertNotIn("setInterval", javascript)
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('preload="none"', html)

    def test_music_events_are_real_actions(self) -> None:
        subscription = self.application.events.subscribe("music.*")
        with self.request("/api/action", body={"action": "music.started"}) as response:
            self.assertTrue(json.load(response)["ok"])
        self.assertEqual(subscription.get(timeout=0.2).type, "music.started")
        subscription.close()

    def test_server_stops_its_thread(self) -> None:
        self.assertTrue(self.application.ui_server.thread_alive)
        self.application.stop()
        self.assertFalse(self.application.ui_server.thread_alive)


if __name__ == "__main__":
    unittest.main()
