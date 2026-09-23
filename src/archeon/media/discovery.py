"""Local-first media resolution without loading playback or networking at idle."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
import os
import time

from .providers import AudiusMediaProvider, JamendoMediaProvider, LocalMediaProvider, MediaSearchResult, YouTubeVisualProvider
from .resolvers import LegacyLocalResolver, YtDlpAuthorizedResolver


class MediaDiscovery:
    def __init__(
        self, data_dir: Path, *, jamendo_client_id: str | None = None,
        youtube_api_key: str | None = None, default_roots: list[Path] | None = None,
    ) -> None:
        self.local = LocalMediaProvider(data_dir / "media-index.json")
        jamendo = JamendoMediaProvider(jamendo_client_id)
        youtube = YouTubeVisualProvider(youtube_api_key)
        allowed_hosts = tuple(filter(None, (
            item.strip() for item in os.environ.get("ARCHEON_YTDLP_ALLOWED_HOSTS", "").split(",")
        )))
        self.authorized_resolver = YtDlpAuthorizedResolver(allowed_hosts)
        self.legacy_local_resolver = LegacyLocalResolver()
        self._online_providers = (
            ([jamendo] if jamendo.available else []) + [AudiusMediaProvider()]
            + ([youtube] if youtube.available else [])
        )
        self._default_roots = default_roots or [Path.home() / "Music", Path.home() / "Downloads"]
        self._results: dict[str, MediaSearchResult] = {}
        self._lock = RLock()

    @property
    def online(self):
        """Compatibility access to the first configured online provider."""
        return self._online_providers[0]

    @online.setter
    def online(self, provider) -> None:
        self._online_providers = [provider]

    def register_online_provider(self, provider) -> None:
        if provider.available and all(item.name != provider.name for item in self._online_providers):
            self._online_providers.append(provider)

    def provider_status(self, *, developer: bool = False) -> list[dict[str, object]]:
        """Return capabilities without contacting a provider."""
        return [
            {"name": "local", "available": True, "kind": "audio", "official_api": True},
            *[
                {"name": provider.name, "available": bool(provider.available),
                 "kind": "visual" if provider.name == "youtube_visual" else "audio", "official_api": True}
                for provider in self._online_providers
            ],
            {"name": self.authorized_resolver.name, "available": self.authorized_resolver.available,
             "kind": "explicit_authorized_source_resolver", "official_api": False},
            {**self.legacy_local_resolver.status(developer=developer),
             "kind": "integrated_local_search_resolver", "official_api": False},
        ]

    def search_legacy(self, query: str, *, limit: int = 8) -> dict[str, object]:
        started = time.perf_counter()
        results = self.legacy_local_resolver.search(query, limit=limit)
        with self._lock:
            for result in results:
                self._results[result.id] = result
            if len(self._results) > 50:
                self._results = dict(list(self._results.items())[-50:])
        return {
            "results": [result.public() for result in results],
            "provider": self.legacy_local_resolver.name,
            "trace": [{
                "provider": self.legacy_local_resolver.name, "query": query,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "candidate_count": len(results), "error": None,
            }],
        }

    def resolve_legacy(self, candidate: MediaSearchResult) -> MediaSearchResult:
        result = self.legacy_local_resolver.resolve(candidate)
        self.remember(result)
        return result

    def refresh(self, roots: list[Path] | None = None) -> dict[str, int]:
        return self.local.refresh(roots or self._default_roots)

    def search(
        self,
        query: str,
        *,
        allow_online: bool,
        limit: int = 10,
        quality: str = "auto",
        include_online_with_local: bool = False,
        query_variants: tuple[str, ...] = (),
    ) -> dict[str, object]:
        started = time.perf_counter()
        if not self.local.has_index:
            self.refresh()
        results = self.local.search(query, limit=limit)
        fallback = False
        provider_errors: list[str] = []
        trace: list[dict[str, object]] = [{
            "provider": "local", "query": query, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "candidate_count": len(results), "error": None,
        }]
        if allow_online and (not results or include_online_with_local):
            combined: list[MediaSearchResult] = list(results)
            seen: set[tuple[str, str]] = {
                (result.title.casefold().strip(), result.artist.casefold().strip()) for result in combined
            }
            searches = tuple(dict.fromkeys(
                " ".join(value.split())[:200]
                for value in (query, *query_variants)
                if isinstance(value, str) and value.strip()
            ))[:5]
            for provider in tuple(self._online_providers):
                if not provider.available:
                    continue
                provider_name = str(getattr(provider, "name", "online"))
                # The official YouTube Data API is a catalog fallback, not an
                # unbounded scraper. One well-formed query per request avoids
                # multiplying quota while native-audio providers can use the
                # bounded spelling variants.
                provider_searches = searches[:1] if provider_name == "youtube_visual" else searches
                for provider_query in provider_searches:
                    attempt_started = time.perf_counter()
                    error_name: str | None = None
                    try:
                        discovered = provider.search(provider_query, limit=limit, quality=quality)
                    except (OSError, RuntimeError, ValueError) as error:
                        error_name = type(error).__name__
                        provider_errors.append(f"{provider_name}:{error_name}")
                        discovered = []
                    trace.append({
                        "provider": provider_name, "query": provider_query,
                        "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 3),
                        "candidate_count": len(discovered), "error": error_name,
                    })
                    for result in discovered:
                        key = (result.title.casefold().strip(), result.artist.casefold().strip())
                        if key in seen:
                            continue
                        seen.add(key)
                        combined.append(result)
            provider_count = len(self._online_providers) * max(1, len(searches)) + int(bool(results))
            results = combined[: max(1, min(50, limit * max(1, provider_count)))]
            fallback = True
        with self._lock:
            self._results = {result.id: result for result in results[:50]}
        return {
            "results": [result.public() for result in results],
            "provider": results[0].provider if len({item.provider for item in results}) <= 1 and results else "multiple" if results else None,
            "online_fallback": fallback,
            "online_available": any(item.available for item in self._online_providers),
            "provider_errors": provider_errors,
            "trace": trace,
            "total_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def resolve(self, result_id: str) -> MediaSearchResult:
        with self._lock:
            result = self._results.get(result_id)
        if result is None:
            raise ValueError("media_result_expired")
        return result

    def remember(self, result: MediaSearchResult) -> None:
        """Keep a bounded, possibly metadata-enriched result for confirmation/playback."""
        with self._lock:
            self._results[result.id] = result
            if len(self._results) > 50:
                self._results = dict(list(self._results.items())[-50:])
