"""Lazy, source-scoped media resolvers.

Resolver != provider != decoder.  This module contains both the strict
allowlisted-source resolver and ARCHEON's integrated broad media search
resolver; neither is imported or started at application idle.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from .providers import MediaSearchResult


class LegacyLocalResolver:
    """Integrated lazy ytsearch resolver used after lighter providers fail.

    Search returns metadata candidates first.  The selected candidate is then
    resolved separately, so TrackMatcher—not result[0]—decides what is played.
    """

    name = "legacy_local"
    DEFAULT_CANDIDATES = 8

    def __init__(self, *, ydl_factory: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._ydl_factory = ydl_factory
        self._last_diagnostics: dict[str, Any] = {
            "state": "idle", "candidate_count": 0, "search_ms": 0.0,
            "resolve_ms": 0.0, "selected_source": None,
        }

    @property
    def installed(self) -> bool:
        return self._ydl_factory is not None or importlib.util.find_spec("yt_dlp") is not None

    def status(self, *, developer: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "enabled": True,
            "installed": self.installed,
            "available": self.installed,
            "state": "ready" if self.installed else "not_installed",
            "api_key_required": False,
            "idle_processes": 0,
        }
        if developer:
            result["diagnostics"] = dict(self._last_diagnostics)
            result["runtime"] = "yt-dlp"
        return result

    def _factory(self):
        if self._ydl_factory is not None:
            return self._ydl_factory
        if not self.installed:
            raise RuntimeError("legacy_local_resolver_not_installed")
        from yt_dlp import YoutubeDL
        return YoutubeDL

    @staticmethod
    def _candidate(entry: dict[str, Any]) -> MediaSearchResult | None:
        identifier = str(entry.get("id") or "").strip()
        if not identifier:
            return None
        source = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if not source.startswith("http"):
            source = f"https://www.youtube.com/watch?v={identifier}"
        channel = str(entry.get("channel") or entry.get("uploader") or "").strip()
        return MediaSearchResult(
            id=f"legacy_local:{identifier}", provider=LegacyLocalResolver.name,
            title=str(entry.get("title") or "").strip() or "Contenido multimedia",
            artist=channel,
            duration_ms=max(0, round(float(entry.get("duration") or 0) * 1000)),
            artwork_url=str(entry.get("thumbnail") or "").strip() or None,
            source_url=source, external_id=identifier,
            playback_kind="resolver_candidate",
            is_verified_artist=bool(entry.get("channel_is_verified")),
            popularity=max(0, int(entry.get("view_count") or 0)),
            artist_source="legacy_local_metadata",
        )

    def search(self, query: str, *, limit: int = DEFAULT_CANDIDATES) -> list[MediaSearchResult]:
        value = " ".join(str(query).split())[:200]
        if not value:
            raise ValueError("legacy_local_query_required")
        limit = max(2, min(12, int(limit)))
        started = time.perf_counter()
        self._last_diagnostics = {
            "state": "searching", "candidate_count": 0, "search_ms": 0.0,
            "resolve_ms": 0.0, "selected_source": None,
        }
        options = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "cachedir": False, "socket_timeout": 12,
            "extract_flat": "in_playlist", "lazy_playlist": False,
            "playlistend": limit, "ignoreconfig": True,
        }
        try:
            with self._factory()(options) as resolver:
                info = resolver.extract_info(f"ytsearch{limit}:{value}", download=False)
        except Exception as error:
            self._last_diagnostics["state"] = "error"
            self._last_diagnostics["error"] = type(error).__name__
            raise RuntimeError("legacy_local_search_failed") from error
        entries = info.get("entries") if isinstance(info, dict) else None
        candidates = [
            candidate for candidate in (
                self._candidate(entry) for entry in (entries or []) if isinstance(entry, dict)
            ) if candidate is not None
        ]
        self._last_diagnostics.update({
            "state": "candidates", "candidate_count": len(candidates),
            "search_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        return candidates

    def resolve(self, candidate: MediaSearchResult) -> MediaSearchResult:
        if candidate.provider != self.name or not candidate.source_url:
            raise ValueError("invalid_legacy_local_candidate")
        started = time.perf_counter()
        options = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "cachedir": False, "socket_timeout": 12,
            "ignoreconfig": True,
            "format": "bestaudio[protocol^=http]/bestaudio/best[protocol^=http]/best",
        }
        try:
            with self._factory()(options) as resolver:
                info = resolver.extract_info(candidate.source_url, download=False)
        except Exception as error:
            self._last_diagnostics["state"] = "resolve_error"
            self._last_diagnostics["error"] = type(error).__name__
            raise RuntimeError("legacy_local_candidate_resolution_failed") from error
        if not isinstance(info, dict):
            raise RuntimeError("legacy_local_candidate_resolution_failed")
        playable = YtDlpAuthorizedResolver._playable_url(info)
        if playable is None:
            raise RuntimeError("legacy_local_playable_source_missing")
        resolved = MediaSearchResult(
            id=candidate.id, provider=self.name,
            title=str(info.get("track") or info.get("title") or candidate.title),
            artist=str(info.get("artist") or info.get("channel") or info.get("uploader") or candidate.artist),
            album=str(info.get("album") or candidate.album),
            duration_ms=max(candidate.duration_ms, round(float(info.get("duration") or 0) * 1000)),
            stream_url=playable,
            artwork_url=str(info.get("thumbnail") or candidate.artwork_url or "") or None,
            source_url=str(info.get("webpage_url") or candidate.source_url),
            playback_kind="native_audio", external_id=candidate.external_id,
            is_verified_artist=bool(info.get("channel_is_verified") or candidate.is_verified_artist),
            popularity=max(candidate.popularity, int(info.get("view_count") or 0)),
            artist_source="legacy_local_resolved_metadata",
        )
        self._last_diagnostics.update({
            "state": "resolved", "resolve_ms": round((time.perf_counter() - started) * 1000, 3),
            "selected_source": resolved.source_url,
        })
        return resolved


class YtDlpAuthorizedResolver:
    """Resolve one explicit allowlisted URL without downloading its media."""

    name = "yt_dlp_authorized"
    FORBIDDEN_HOSTS = frozenset({
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
        "youtu.be", "googlevideo.com",
    })

    def __init__(
        self, allowed_hosts: tuple[str, ...] = (), *,
        ydl_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._allowed_hosts = tuple(
            host.casefold().strip().lstrip(".") for host in allowed_hosts if host.strip()
        )
        self._ydl_factory = ydl_factory

    @property
    def available(self) -> bool:
        return bool(self._allowed_hosts) and (
            self._ydl_factory is not None or importlib.util.find_spec("yt_dlp") is not None
        )

    @classmethod
    def _host_for(cls, source: str) -> str:
        parsed = urllib.parse.urlparse(source)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not host or host.endswith(".local") or host == "localhost":
            raise ValueError("authorized_media_source_must_be_public_https")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and any((address.is_private, address.is_loopback, address.is_link_local, address.is_reserved)):
            raise ValueError("authorized_media_source_must_be_public_https")
        if host in cls.FORBIDDEN_HOSTS or any(host.endswith("." + item) for item in cls.FORBIDDEN_HOSTS):
            raise ValueError("youtube_requires_official_visible_player")
        return host

    def _validate_source(self, source: str) -> str:
        host = self._host_for(source)
        if not any(host == allowed or host.endswith("." + allowed) for allowed in self._allowed_hosts):
            raise ValueError("media_source_host_not_authorized")
        return source

    @staticmethod
    def _playable_url(info: dict[str, Any]) -> str | None:
        candidates = [info]
        formats = info.get("formats")
        if isinstance(formats, list):
            candidates.extend(item for item in reversed(formats) if isinstance(item, dict))
        for item in candidates:
            value = item.get("url")
            protocol = str(item.get("protocol") or "https").casefold()
            if (
                isinstance(value, str) and value.startswith("https://")
                and str(item.get("acodec") or "unknown") != "none"
                and protocol not in {"m3u8_native_live", "rtmp", "rtsp"}
            ):
                return value
        return None

    def resolve(self, source: str) -> MediaSearchResult:
        source = self._validate_source(str(source).strip())
        if not self.available:
            raise RuntimeError("yt_dlp_authorized_resolver_unavailable")
        if self._ydl_factory is None:
            from yt_dlp import YoutubeDL
            factory = YoutubeDL
        else:
            factory = self._ydl_factory
        options = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "cachedir": False, "socket_timeout": 10,
            "extract_flat": False,
        }
        with factory(options) as resolver:
            info = resolver.extract_info(source, download=False)
        if not isinstance(info, dict):
            raise RuntimeError("authorized_media_resolution_failed")
        entries = info.get("entries")
        if isinstance(entries, list):
            info = next((item for item in entries if isinstance(item, dict)), {})
        playable = self._playable_url(info)
        if playable is None:
            raise RuntimeError("authorized_media_playable_source_missing")
        identifier = str(info.get("id") or abs(hash(source)))
        return MediaSearchResult(
            id=f"yt_dlp_authorized:{identifier}", provider=self.name,
            title=str(info.get("title") or "Contenido autorizado"),
            artist=str(info.get("artist") or info.get("uploader") or ""),
            duration_ms=max(0, round(float(info.get("duration") or 0) * 1000)),
            stream_url=playable, artwork_url=str(info.get("thumbnail") or "") or None,
            source_url=source, playback_kind="native_audio",
            artist_source="authorized_source_metadata",
        )
