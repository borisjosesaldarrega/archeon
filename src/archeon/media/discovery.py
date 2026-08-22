"""Local-first media resolution without loading playback or networking at idle."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from .providers import JamendoMediaProvider, LocalMediaProvider, MediaSearchResult


class MediaDiscovery:
    def __init__(self, data_dir: Path, *, jamendo_client_id: str | None = None, default_roots: list[Path] | None = None) -> None:
        self.local = LocalMediaProvider(data_dir / "media-index.json")
        self.online = JamendoMediaProvider(jamendo_client_id)
        self._default_roots = default_roots or [Path.home() / "Music", Path.home() / "Downloads"]
        self._results: dict[str, MediaSearchResult] = {}
        self._lock = RLock()

    def refresh(self, roots: list[Path] | None = None) -> dict[str, int]:
        return self.local.refresh(roots or self._default_roots)

    def search(self, query: str, *, allow_online: bool, limit: int = 10, quality: str = "auto") -> dict[str, object]:
        if not self.local.has_index:
            self.refresh()
        results = self.local.search(query, limit=limit)
        fallback = False
        if not results and allow_online:
            if not self.online.available:
                raise RuntimeError("online_media_provider_unconfigured")
            results = self.online.search(query, limit=limit, quality=quality)
            fallback = True
        with self._lock:
            self._results = {result.id: result for result in results[:50]}
        return {
            "results": [result.public() for result in results],
            "provider": results[0].provider if results else None,
            "online_fallback": fallback,
            "online_available": self.online.available,
        }

    def resolve(self, result_id: str) -> MediaSearchResult:
        with self._lock:
            result = self._results.get(result_id)
        if result is None:
            raise ValueError("media_result_expired")
        return result
