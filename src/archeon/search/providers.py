"""Lightweight cited web-search provider with no startup network activity."""

from __future__ import annotations

import json
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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


class GoogleNewsRssProvider:
    """Keyless, on-demand current-news fallback; it performs no idle polling."""

    name = "google-news-rss"
    ENDPOINT = "https://news.google.com/rss/search"

    def __init__(self, *, opener: Callable[..., BinaryIO] = urllib.request.urlopen) -> None:
        self._opener = opener

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, *, limit: int = 5, language: str = "es", freshness: str | None = None) -> list[SearchResult]:
        query = " ".join(query.split())[:400]
        if not query:
            return []
        if freshness == "pd" and "when:" not in query.casefold():
            query = f"{query} when:1d"
        elif freshness == "pw" and "when:" not in query.casefold():
            query = f"{query} when:7d"
        language = language[:2].casefold()
        locale = {"es": ("es-419", "EC", "EC:es-419"), "en": ("en-US", "US", "US:en")}.get(
            language, (language, "US", f"US:{language}")
        )
        request = urllib.request.Request(
            f"{self.ENDPOINT}?{urllib.parse.urlencode({'q': query, 'hl': locale[0], 'gl': locale[1], 'ceid': locale[2]})}",
            headers={"Accept": "application/rss+xml, application/xml", "User-Agent": "ARCHEON/10"},
        )
        with self._opener(request, timeout=8) as response:
            body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise RuntimeError("search_provider_response_too_large")
        root = ET.fromstring(body)
        retrieved_at = datetime.now(UTC).isoformat()
        results: list[SearchResult] = []
        for item in root.findall("./channel/item")[:max(1, min(20, limit))]:
            url = (item.findtext("link") or "").strip()
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            source_node = item.find("source")
            source = ((source_node.text or "").strip() if source_node is not None else "") or parsed.hostname
            raw_description = item.findtext("description") or ""
            description = html.unescape(re.sub(r"<[^>]+>", " ", raw_description))
            description = " ".join(description.split())[:500]
            results.append(SearchResult(
                title=(item.findtext("title") or "").strip(), url=url,
                description=description, source=source,
                published=(item.findtext("pubDate") or "").strip() or None,
                retrieved_at=retrieved_at,
            ))
        return results
