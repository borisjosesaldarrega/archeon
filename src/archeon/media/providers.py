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
    release: str | None = None
    is_verified_artist: bool = False
    popularity: int = 0
    artist_source: str | None = None
    playback_kind: str = "native_audio"
    external_id: str | None = None

    def public(self) -> dict[str, object]:
        return asdict(self)


class MediaProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]: ...


class OnlineMediaProvider(MediaProvider, Protocol):
    """Network catalog contract; MediaEngine only consumes MediaSearchResult."""


class SystemMediaProvider(Protocol):
    """Future Windows Media Foundation/native catalog contract."""

    name: str
    def resolve(self, source: str) -> MediaSearchResult: ...


class OptionalCodecProvider(Protocol):
    """Optional small codec contract; never a mandatory MediaEngine dependency."""

    name: str
    def supports(self, content_type: str) -> bool: ...


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


class AudiusMediaProvider:
    """Official Audius catalog search with a playable, on-demand stream URL."""

    name = "audius"
    ENDPOINT = "https://api.audius.co/v1/tracks/search"
    STREAM_ENDPOINT = "https://api.audius.co/v1/tracks/{track_id}/stream?app_name=ARCHEON"

    def __init__(self, *, opener: OpenUrl = urllib.request.urlopen) -> None:
        self._opener = opener

    @property
    def available(self) -> bool:
        return True

    @staticmethod
    def _https_url(value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = urllib.parse.urlparse(value)
        return value if parsed.scheme == "https" and parsed.hostname else None

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]:
        del quality
        query = " ".join(query.split())[:200]
        if not query:
            return []
        parameters = urllib.parse.urlencode({"query": query, "app_name": "ARCHEON"})
        request = urllib.request.Request(
            f"{self.ENDPOINT}?{parameters}",
            headers={"Accept": "application/json", "User-Agent": "ARCHEON/10"},
        )
        with self._opener(request, timeout=8) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("media_provider_response_too_large")
        payload = json.loads(body.decode("utf-8"))
        results: list[MediaSearchResult] = []
        for item in payload.get("data", []):
            track_id = str(item.get("id") or "")
            if not track_id or bool(item.get("is_stream_gated")):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            artwork = item.get("artwork") if isinstance(item.get("artwork"), dict) else {}
            permalink = str(item.get("permalink") or "")
            source_url = self._https_url(f"https://audius.co{permalink}" if permalink.startswith("/") else permalink)
            results.append(MediaSearchResult(
                id=f"audius:{track_id}", provider=self.name,
                title=str(item.get("title") or ""), artist=str(user.get("name") or ""),
                album=str(item.get("album_name") or ""),
                duration_ms=max(0, int(item.get("duration") or 0) * 1000),
                stream_url=self.STREAM_ENDPOINT.format(track_id=urllib.parse.quote(track_id, safe="")),
                artwork_url=self._https_url(artwork.get("480x480") or artwork.get("150x150")),
                source_url=source_url,
                license_url=self._https_url(item.get("license")),
                release=str(item.get("release_date") or "") or None,
                is_verified_artist=bool(user.get("is_verified")),
                popularity=max(0, int(item.get("play_count") or 0)),
            ))
            if len(results) >= max(1, min(20, limit)):
                break
        return results


class YouTubeVisualProvider:
    """Official YouTube Data API metadata for a visible IFrame player.

    This provider never resolves or exposes an audio stream URL.  Search and
    playback remain separate: results carry a video id to the official player.
    """

    name = "youtube_visual"
    ENDPOINT = "https://www.googleapis.com/youtube/v3/search"

    def __init__(self, api_key: str | None, *, opener: OpenUrl = urllib.request.urlopen) -> None:
        self._api_key = (api_key or "").strip()
        self._opener = opener

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _thumbnail(snippet: dict[str, object]) -> str | None:
        thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
        for key in ("maxres", "high", "medium", "default"):
            item = thumbnails.get(key) if isinstance(thumbnails, dict) else None
            value = item.get("url") if isinstance(item, dict) else None
            if isinstance(value, str) and value.startswith("https://"):
                return value
        return None

    def search(self, query: str, *, limit: int = 10, quality: str = "auto") -> list[MediaSearchResult]:
        del quality
        if not self.available:
            raise RuntimeError("youtube_api_key_required")
        query = " ".join(query.split())[:200]
        if not query:
            return []
        parameters = urllib.parse.urlencode({
            "part": "snippet", "type": "video", "videoEmbeddable": "true",
            "maxResults": max(1, min(20, limit)), "order": "relevance",
            "q": query, "key": self._api_key,
        })
        request = urllib.request.Request(
            f"{self.ENDPOINT}?{parameters}",
            headers={"Accept": "application/json", "User-Agent": "ARCHEON/10"},
        )
        with self._opener(request, timeout=8) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("media_provider_response_too_large")
        payload = json.loads(body.decode("utf-8"))
        results: list[MediaSearchResult] = []
        for item in payload.get("items", []):
            identifier = item.get("id") if isinstance(item, dict) else None
            snippet = item.get("snippet") if isinstance(item, dict) else None
            video_id = identifier.get("videoId") if isinstance(identifier, dict) else None
            if not isinstance(video_id, str) or not video_id or not isinstance(snippet, dict):
                continue
            results.append(MediaSearchResult(
                id=f"youtube_visual:{video_id}", provider=self.name,
                title=str(snippet.get("title") or ""), artist=str(snippet.get("channelTitle") or ""),
                artwork_url=self._thumbnail(snippet),
                source_url=f"https://www.youtube.com/watch?v={urllib.parse.quote(video_id, safe='')}",
                playback_kind="official_web", external_id=video_id,
                artist_source="youtube_channel_metadata",
            ))
        return results
