"""Short-lived cited search cache around an optional on-demand provider."""

from __future__ import annotations

import time
from threading import RLock

from .providers import BraveSearchProvider, SearchResult


class SearchEngine:
    CACHE_SECONDS = 300

    def __init__(self, provider: BraveSearchProvider) -> None:
        self.provider = provider
        self._cache: dict[tuple[str, str, str | None], tuple[float, list[SearchResult]]] = {}
        self._lock = RLock()

    @property
    def available(self) -> bool:
        return self.provider.available

    def search(self, query: str, *, limit: int = 5, language: str = "es", freshness: str | None = None) -> list[dict[str, object]]:
        key = (" ".join(query.casefold().split()), language[:2], freshness)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] <= self.CACHE_SECONDS:
                return [result.public() for result in cached[1][:limit]]
        results = self.provider.search(query, limit=limit, language=language, freshness=freshness)
        with self._lock:
            if len(self._cache) >= 20:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)
            self._cache[key] = (now, results)
        return [result.public() for result in results]
