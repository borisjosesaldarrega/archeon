from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archeon.launcher import LauncherEngine


class LauncherTests(unittest.TestCase):
    def test_epic_manifest_is_hidden_when_install_directory_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = root / "Epic/EpicGamesLauncher/Data/Manifests"
            manifests.mkdir(parents=True)
            (manifests / "stale.item").write_text(
                '{"AppName":"StaleGame","DisplayName":"Juego desinstalado","InstallLocation":"C:/missing/archeon-test-game"}',
                encoding="utf-8",
            )
            engine = LauncherEngine(root / "data")
            engine._scan_start_menus = lambda: None
            engine._scan_registry = lambda: None
            engine._steam_roots = lambda: []
            with patch.dict("os.environ", {"PROGRAMDATA": str(root)}, clear=False):
                items = engine.refresh(force=True)
            self.assertEqual(items, [])

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
            portable = engine.portable_state()
            self.assertEqual(portable["favorites"], [{"name": "Example App", "kind": "app"}])
            engine._launcher_state = {"favorites": [], "recent": [], "aliases": {}}
            engine.apply_portable_state(portable)
            self.assertEqual(engine.command_item("abre mi ejemplo").name, "Example App")
            stored = (root / "data/launcher.json").read_text(encoding="utf-8")
            self.assertNotIn(str(shortcut), stored)

    def test_non_launcher_command_does_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine = LauncherEngine(Path(temporary))
            engine._scan_start_menus = lambda: None
            engine._scan_registry = lambda: None
            engine._scan_games = lambda: None
            self.assertIsNone(engine.command_item("estado del sistema"))

    def test_speech_catalog_deduplicates_same_app_from_multiple_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine = LauncherEngine(Path(temporary))
            engine._add("Steam", "C:/one/Steam.lnk", "app", "start-menu")
            engine._add("Steam", "C:/two/Steam.exe", "app", "registry")
            engine._loaded_at = __import__("time").monotonic()
            catalog = engine.speech_catalog()
            self.assertEqual(len(catalog), 1)
            self.assertEqual(catalog[0]["name"], "Steam")
            self.assertEqual(engine._items[catalog[0]["id"]].source, "start-menu")

    def test_custom_shortcut_is_device_local_and_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "My Tool.exe"
            target.write_bytes(b"MZ")
            engine = LauncherEngine(root / "data")
            engine._scan_start_menus = lambda: None
            engine._scan_registry = lambda: None
            engine._scan_games = lambda: None
            item = engine.add_custom("Mi herramienta", str(target))
            self.assertEqual(item["source"], "custom")
            engine.refresh(force=True)
            self.assertEqual(engine.command_item("abre mi herramienta").target, str(target.resolve()))
            self.assertNotIn("custom", engine.portable_state())


if __name__ == "__main__":
    unittest.main()
