from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from archeon.audio import AudioManager, AudioMode
from archeon.core.events import EventBus
from archeon.plugins import PluginManager


class _Backend:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.config = None

    def open(self, config) -> None:
        self.opened = True
        self.config = config

    def close(self) -> None:
        self.closed = True


class AudioAndPluginTests(unittest.TestCase):
    def test_audio_backend_is_lazy_shared_and_released(self) -> None:
        events = EventBus()
        manager = AudioManager(events)
        made: list[_Backend] = []
        manager.register_backend("wasapi_shared", lambda: made.append(_Backend()) or made[-1])
        manager.start()
        self.assertFalse(manager.backend_loaded)
        manager.acquire(AudioMode.CAPTURING)
        self.assertTrue(made[0].config.shared)
        self.assertFalse(made[0].config.exclusive)
        manager.stop()
        self.assertTrue(made[0].closed)
        self.assertFalse(manager.backend_loaded)

    def test_plugin_scan_does_not_import_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_dir = root / "demo"
            manifest_dir.mkdir()
            (manifest_dir / "plugin.json").write_text(
                json.dumps({"id": "demo.plugin", "version": "1", "entrypoint": "never_loaded:make"}),
                encoding="utf-8",
            )
            manager = PluginManager(EventBus(), root)
            manager.start()
            manifests = manager.scan()
            self.assertEqual(manifests[0].plugin_id, "demo.plugin")
            self.assertNotIn("never_loaded", sys.modules)
            manager.stop()


if __name__ == "__main__":
    unittest.main()
