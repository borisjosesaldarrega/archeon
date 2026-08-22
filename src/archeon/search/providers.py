"""Lightweight cited web-search provider with no startup network activity."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import BinaryIO, Callable


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    description: str
    source: str
    published: str | None = None
    retrieved_at: str = ""

    def public(self) -> dict[str, object]:
        return asdict(self)


class BraveSearchProvider:
    name = "brave"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None, *, opener: Callable[..., BinaryIO] = urllib.request.urlopen) -> None:
        self._api_key = (api_key or "").strip()
        self._opener = opener

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, *, limit: int = 5, language: str = "es", freshness: str | None = None) -> list[SearchResult]:
        if not self.available:
            raise RuntimeError("brave_api_key_required")
        query = " ".join(query.split())[:400]
        if not query:
            return []
        params: dict[str, object] = {"q": query, "count": max(1, min(20, limit)), "search_lang": language[:2], "safesearch": "moderate"}
        if freshness in {"pd", "pw", "pm", "py"}:
            params["freshness"] = freshness
        request = urllib.request.Request(
            f"{self.ENDPOINT}?{urllib.parse.urlencode(params)}",
            headers={"Accept": "application/json", "X-Subscription-Token": self._api_key, "User-Agent": "ARCHEON/10"},
        )
        with self._opener(request, timeout=8) as response:
            body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise RuntimeError("search_provider_response_too_large")
        payload = json.loads(body.decode("utf-8"))
        retrieved_at = datetime.now(UTC).isoformat()
        results: list[SearchResult] = []
        for item in payload.get("web", {}).get("results", []):
            url = str(item.get("url") or "")
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            results.append(SearchResult(
                title=str(item.get("title") or ""), url=url,
                description=str(item.get("description") or ""), source=parsed.hostname,
                published=str(item["age"]) if item.get("age") else None, retrieved_at=retrieved_at,
            ))
        return results
