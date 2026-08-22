"""Bounded launcher discovery with an atomic local cache and no polling."""

from __future__ import annotations

import ctypes
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from archeon.core.lifecycle import ManagedComponent


@dataclass(frozen=True, slots=True)
class LaunchItem:
    id: str
    name: str
    target: str
    kind: str
    source: str


class LauncherEngine(ManagedComponent):
    CACHE_SECONDS = 900

    def __init__(self, data_dir: Path) -> None:
        super().__init__("launcher")
        self._path = data_dir / "launcher.json"
        self._lock = RLock()
        self._items: dict[str, LaunchItem] = {}
        self._loaded_at = 0.0
        self._launcher_state: dict[str, Any] = {"favorites": [], "recent": [], "aliases": {}}

    @property
    def loaded(self) -> bool:
        return bool(self._items)

    @staticmethod
    def normalize(value: str) -> str:
        text = unicodedata.normalize("NFKD", value.casefold())
        return " ".join("".join(c for c in text if c.isalnum() or c.isspace()).split())

    @classmethod
    def _id(cls, source: str, target: str) -> str:
        import hashlib
        return hashlib.sha256(f"{source}\0{target}".encode()).hexdigest()[:20]

    def _read_state(self) -> None:
        if not self._path.is_file():
            return
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                self._launcher_state.update({key: value.get(key, self._launcher_state[key]) for key in self._launcher_state})
        except (OSError, ValueError, json.JSONDecodeError):
            return

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._launcher_state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)

    def _add(self, name: str, target: str, kind: str, source: str) -> None:
        name, target = name.strip(), target.strip().strip('"')
        if not name or not target:
            return
        item = LaunchItem(self._id(source, target), name, target, kind, source)
        self._items.setdefault(item.id, item)

    def _scan_start_menus(self) -> None:
        roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in ("*.lnk", "*.url", "*.appref-ms"):
                for path in root.rglob(pattern):
                    self._add(path.stem, str(path), "app", "start-menu")

    def _scan_registry(self) -> None:
        if os.name != "nt":
            return
        import winreg
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, location in locations:
            try:
                root = winreg.OpenKey(hive, location)
            except OSError:
                continue
            with root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                            name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                            target = ""
                            for field in ("DisplayIcon", "InstallLocation"):
                                try:
                                    target = str(winreg.QueryValueEx(key, field)[0]).split(",", 1)[0]
                                    if target:
                                        break
                                except OSError:
                                    pass
                            if target and Path(target.strip('"')).is_file():
                                self._add(name, target, "app", "registry")
                    except OSError:
                        continue

    def _steam_roots(self) -> list[Path]:
        roots: list[Path] = []
        if os.name == "nt":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    roots.append(Path(str(winreg.QueryValueEx(key, "SteamPath")[0])))
            except OSError:
                pass
        for root in tuple(roots):
            library = root / "steamapps/libraryfolders.vdf"
            if library.is_file():
                try:
                    for value in re.findall(r'"path"\s+"([^"]+)"', library.read_text(encoding="utf-8", errors="ignore")):
                        roots.append(Path(value.replace("\\\\", "\\")))
                except OSError:
                    pass
        return list(dict.fromkeys(roots))

    def _scan_games(self) -> None:
        for root in self._steam_roots():
            for manifest in (root / "steamapps").glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                    appid = re.search(r'"appid"\s+"(\d+)"', text)
                    name = re.search(r'"name"\s+"([^"]+)"', text)
                    if appid and name:
                        self._add(name.group(1), f"steam://rungameid/{appid.group(1)}", "game", "steam")
                except OSError:
                    pass
        epic = Path(os.environ.get("PROGRAMDATA", "")) / "Epic/EpicGamesLauncher/Data/Manifests"
        if epic.is_dir():
            for manifest in epic.glob("*.item"):
                try:
                    value = json.loads(manifest.read_text(encoding="utf-8"))
                    app = str(value.get("AppName") or value.get("CatalogItemId") or "")
                    self._add(str(value.get("DisplayName") or app), f"com.epicgames.launcher://apps/{app}?action=launch&silent=true", "game", "epic")
                except (OSError, ValueError, json.JSONDecodeError):
                    pass

    def refresh(self, *, force: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if self._items and not force and time.monotonic() - self._loaded_at < self.CACHE_SECONDS:
                return self.list_items()
            self._items.clear()
            self._scan_start_menus()
            self._scan_registry()
            self._scan_games()
            self._loaded_at = time.monotonic()
            return self.list_items()

    def list_items(self, category: str = "all") -> list[dict[str, Any]]:
        favorites = set(self._launcher_state["favorites"])
        recent = list(self._launcher_state["recent"])
        values = list(self._items.values())
        if category == "favorites":
            values = [item for item in values if item.id in favorites]
        elif category == "recent":
            order = {item_id: index for index, item_id in enumerate(recent)}
            values = sorted((item for item in values if item.id in order), key=lambda item: order[item.id])
        elif category in {"app", "game"}:
            values = [item for item in values if item.kind == category]
        else:
            values.sort(key=lambda item: (item.kind, self.normalize(item.name)))
        return [asdict(item) | {"favorite": item.id in favorites} for item in values]

    def launch(self, item_id: str) -> dict[str, Any]:
        self.refresh()
        item = self._items.get(item_id)
        if item is None:
            raise ValueError("launcher_item_not_found")
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", item.target, None, None, 1)
        if int(result) <= 32:
            raise OSError(f"launch_failed:{int(result)}")
        recent = [item.id, *[value for value in self._launcher_state["recent"] if value != item.id]][:20]
        self._launcher_state["recent"] = recent
        self._save()
        return asdict(item) | {"accepted_by_windows": True}

    def favorite(self, item_id: str, enabled: bool) -> None:
        self.refresh()
        if item_id not in self._items:
            raise ValueError("launcher_item_not_found")
        values = set(self._launcher_state["favorites"])
        values.add(item_id) if enabled else values.discard(item_id)
        self._launcher_state["favorites"] = sorted(values)
        self._save()

    def set_alias(self, alias: str, item_id: str) -> None:
        self.refresh()
        normalized = self.normalize(alias)
        if not normalized or item_id not in self._items:
            raise ValueError("invalid_launcher_alias")
        self._launcher_state["aliases"][normalized] = item_id
        self._save()

    def portable_state(self) -> dict[str, list[dict[str, str]]]:
        """Export favorites and aliases without leaking local targets or identifiers."""
        self.refresh()
        favorites = set(self._launcher_state["favorites"])
        favorite_items = [
            {"name": item.name, "kind": item.kind}
            for item in self._items.values() if item.id in favorites
        ]
        aliases = []
        for alias, item_id in self._launcher_state["aliases"].items():
            item = self._items.get(item_id)
            if item is not None:
                aliases.append({"alias": alias, "name": item.name, "kind": item.kind})
        return {"favorites": favorite_items, "aliases": aliases}

    def apply_portable_state(self, value: dict[str, Any]) -> None:
        """Resolve portable names against this machine's bounded local catalog."""
        self.refresh()
        by_key = {(self.normalize(item.name), item.kind): item.id for item in self._items.values()}
        favorites: set[str] = set()
        for entry in value.get("favorites", []):
            if isinstance(entry, dict):
                item_id = by_key.get((self.normalize(str(entry.get("name", ""))), str(entry.get("kind", ""))))
                if item_id:
                    favorites.add(item_id)
        aliases: dict[str, str] = {}
        for entry in value.get("aliases", []):
            if isinstance(entry, dict):
                item_id = by_key.get((self.normalize(str(entry.get("name", ""))), str(entry.get("kind", ""))))
                alias = self.normalize(str(entry.get("alias", "")))
                if item_id and alias:
                    aliases[alias] = item_id
        self._launcher_state["favorites"] = sorted(favorites)
        self._launcher_state["aliases"] = aliases
        self._save()

    def command_item(self, text: str) -> LaunchItem | None:
        self.refresh()
        normalized = self.normalize(text)
        prefixes = ("abre ", "abrir ", "open ", "launch ", "ouvre ", "ouvrir ")
        query = next((normalized[len(prefix):] for prefix in prefixes if normalized.startswith(prefix)), "")
        if not query:
            return None
        alias_id = self._launcher_state["aliases"].get(query)
        if alias_id in self._items:
            return self._items[alias_id]
        exact = [item for item in self._items.values() if self.normalize(item.name) == query]
        return exact[0] if len(exact) == 1 else None

    def _start(self) -> None:
        self._read_state()

    def _stop(self) -> None:
        self._items.clear()
