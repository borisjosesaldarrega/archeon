"""Lazy local and official-online media discovery providers."""

from __future__ import annotations

import json
import hashlib
import os
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Callable, Protocol


AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"})


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


@dataclass(frozen=True, slots=True)
class MediaSearchResult:
    id: str
    provider: str
    title: str
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    local_path: str | None = None
    stream_url: str | None = None
    artwork_url: str | None = None
    source_url: str | None = None
    license_url: str | None = None

    def public(self) -> dict[str, object]:
        return asdict(self)


class MediaProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]: ...


class LocalMediaProvider:
    """Explicitly refreshed bounded index; never scans at application startup."""

    name = "local"
    MAX_FILES = 25_000

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path
        self._items: list[dict[str, object]] | None = None

    @property
    def available(self) -> bool:
        return True

    @property
    def has_index(self) -> bool:
        return self._index_path.is_file()

    def refresh(self, roots: list[Path]) -> dict[str, int]:
        items: list[dict[str, object]] = []
        visited = 0
        for root in roots:
            resolved = root.expanduser().resolve()
            if not resolved.is_dir():
                continue
            for directory, names, files in os.walk(resolved, followlinks=False):
                names[:] = [name for name in names if not name.startswith(".")]
                for filename in files:
                    visited += 1
                    if visited > self.MAX_FILES:
                        break
                    path = Path(directory) / filename
                    if path.suffix.casefold() not in AUDIO_SUFFIXES:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    items.append({"path": str(path), "name": path.stem, "mtime_ns": stat.st_mtime_ns, "bytes": stat.st_size})
                if visited > self.MAX_FILES:
                    break
            if visited > self.MAX_FILES:
                break
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": items}
        with NamedTemporaryFile("w", encoding="utf-8", dir=self._index_path.parent, delete=False) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, self._index_path)
        self._items = items
        return {"indexed": len(items), "visited": min(visited, self.MAX_FILES), "truncated": int(visited > self.MAX_FILES)}

    def _load(self) -> list[dict[str, object]]:
        if self._items is not None:
            return self._items
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
            items = payload.get("items", []) if payload.get("version") == 1 else []
            self._items = items if isinstance(items, list) else []
        except (OSError, ValueError, AttributeError):
            self._items = []
        return self._items

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]:
        del quality
        terms = tuple(_normalized(query).split())
        if not terms:
            return []
        ranked: list[tuple[int, str, dict[str, object]]] = []
        for item in self._load():
            name = str(item.get("name", ""))
            path = str(item.get("path", ""))
            haystack = _normalized(f"{name} {path}")
            if not all(term in haystack for term in terms):
                continue
            exact = int(_normalized(name) == " ".join(terms))
            prefix = sum(int(_normalized(name).startswith(term)) for term in terms)
            ranked.append((exact * 100 + prefix * 10, name.casefold(), item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        return [
            MediaSearchResult(
                id=f"local:{hashlib.sha256(str(item['path']).encode('utf-8')).hexdigest()[:20]}", provider=self.name,
                title=str(item["name"]), artist="Artista local", local_path=str(item["path"]),
            )
            for _score, _name, item in ranked[: max(1, min(50, limit))]
        ]


OpenUrl = Callable[..., BinaryIO]


class JamendoMediaProvider:
    """Official Jamendo search/stream metadata; performs network I/O only in search()."""

    name = "jamendo"
    ENDPOINT = "https://api.jamendo.com/v3.0/tracks/"
    QUALITY = {"low": "mp31", "medium": "mp32", "high": "flac", "auto": "mp32"}

    def __init__(self, client_id: str | None, *, opener: OpenUrl = urllib.request.urlopen) -> None:
        self._client_id = (client_id or "").strip()
        self._opener = opener

    @property
    def available(self) -> bool:
        return bool(self._client_id)

    @staticmethod
    def _trusted_url(value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (host == "jamendo.com" or host.endswith(".jamendo.com")):
            return None
        return value

    @staticmethod
    def _metadata_url(value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").casefold()
        if host == "creativecommons.org" and parsed.scheme in {"http", "https"}:
            return urllib.parse.urlunparse(parsed._replace(scheme="https"))
        return JamendoMediaProvider._trusted_url(value)

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]:
        if not self.available:
            raise RuntimeError("jamendo_client_id_required")
        query = " ".join(query.split())[:200]
        if not query:
            return []
        parameters = urllib.parse.urlencode({
            "client_id": self._client_id, "format": "json", "limit": max(1, min(20, limit)),
            "search": query, "order": "relevance", "type": "single albumtrack", "imagesize": 300,
            "audioformat": self.QUALITY.get(quality.casefold(), self.QUALITY["auto"]),
        })
        request = urllib.request.Request(f"{self.ENDPOINT}?{parameters}", headers={"Accept": "application/json", "User-Agent": "ARCHEON/10"})
        with self._opener(request, timeout=8) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("media_provider_response_too_large")
        payload = json.loads(body.decode("utf-8"))
        if payload.get("headers", {}).get("status") != "success":
            raise RuntimeError("jamendo_search_failed")
        results: list[MediaSearchResult] = []
        for item in payload.get("results", []):
            stream_url = self._trusted_url(item.get("audio"))
            if stream_url is None:
                continue
            results.append(MediaSearchResult(
                id=f"jamendo:{item.get('id', '')}", provider=self.name,
                title=str(item.get("name") or ""), artist=str(item.get("artist_name") or ""),
                album=str(item.get("album_name") or ""), duration_ms=max(0, int(item.get("duration") or 0) * 1000),
                stream_url=stream_url, artwork_url=self._trusted_url(item.get("image") or item.get("album_image")),
                source_url=self._trusted_url(item.get("shareurl")), license_url=self._metadata_url(item.get("license_ccurl")),
            ))
        return results
