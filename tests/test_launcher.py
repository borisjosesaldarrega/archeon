from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archeon.launcher import LauncherEngine


class LauncherTests(unittest.TestCase):
    def test_start_menu_discovery_favorites_aliases_and_cache_are_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shortcut = root / "Microsoft/Windows/Start Menu/Programs/Example App.lnk"
            shortcut.parent.mkdir(parents=True)
            shortcut.write_bytes(b"shortcut")
            engine = LauncherEngine(root / "data")
            engine._scan_registry = lambda: None
            engine._scan_games = lambda: None
            with patch.dict("os.environ", {"APPDATA": str(root), "PROGRAMDATA": str(root / "system")}, clear=False):
                items = engine.refresh()
            self.assertEqual(len(items), 1)
            item = items[0]
            engine.favorite(item["id"], True)
            engine.set_alias("mi ejemplo", item["id"])
            self.assertEqual(engine.command_item("abre mi ejemplo").id, item["id"])
            self.assertEqual(engine.command_item("open Example App").id, item["id"])
            self.assertEqual(engine.list_items("favorites")[0]["name"], "Example App")
            stored = (root / "data/launcher.json").read_text(encoding="utf-8")
            self.assertNotIn(str(shortcut), stored)

    def test_non_launcher_command_does_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine = LauncherEngine(Path(temporary))
            engine._scan_start_menus = lambda: None
            engine._scan_registry = lambda: None
            engine._scan_games = lambda: None
            self.assertIsNone(engine.command_item("estado del sistema"))


if __name__ == "__main__":
    unittest.main()
