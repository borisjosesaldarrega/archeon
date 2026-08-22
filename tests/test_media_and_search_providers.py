from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from archeon.media.discovery import MediaDiscovery
from archeon.media.providers import MediaSearchResult
from archeon.media.providers import JamendoMediaProvider, LocalMediaProvider
from archeon.search.engine import SearchEngine
from archeon.search.providers import BraveSearchProvider


class ProviderTests(unittest.TestCase):
    def test_local_media_index_is_explicit_cached_and_accent_tolerant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music = root / "Music"
            music.mkdir()
            track = music / "Canción Única.mp3"
            track.write_bytes(b"not-decoded-during-index")
            provider = LocalMediaProvider(root / "media-index.json")
            self.assertEqual(provider.search("cancion"), [])
            stats = provider.refresh([music])
            self.assertEqual(stats["indexed"], 1)
            result = provider.search("cancion unica")[0]
            self.assertEqual(result.local_path, str(track))
            self.assertEqual(result.provider, "local")
            restored = LocalMediaProvider(root / "media-index.json")
            self.assertEqual(restored.search("unica")[0].id, result.id)

    def test_jamendo_provider_is_lazy_official_and_rejects_untrusted_streams(self) -> None:
        calls = []
        payload = {
            "headers": {"status": "success"},
            "results": [
                {
                    "id": "12", "name": "Light", "artist_name": "Artist", "album_name": "Album",
                    "duration": 123, "audio": "https://prod-1.storage.jamendo.com/track.mp3",
                    "image": "https://usercontent.jamendo.com/cover.jpg", "shareurl": "https://www.jamendo.com/track/12",
                    "license_ccurl": "http://creativecommons.org/licenses/by/4.0/",
                },
                {"id": "13", "name": "Unsafe", "audio": "https://example.test/track.mp3"},
            ],
        }

        def opener(request, *, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps(payload).encode())

        provider = JamendoMediaProvider("client", opener=opener)
        self.assertEqual(calls, [])
        results = provider.search("light", quality="low")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].duration_ms, 123_000)
        self.assertTrue(results[0].license_url.startswith("https://creativecommons.org/"))
        self.assertIn("audioformat=mp31", calls[0][0].full_url)
        self.assertNotIn("client", repr(results[0]))
        with self.assertRaisesRegex(RuntimeError, "client_id"):
            JamendoMediaProvider(None).search("track")

    def test_brave_provider_returns_temporary_cited_results_without_leaking_key(self) -> None:
        calls = []
        payload = {"web": {"results": [
            {"title": "Current source", "url": "https://news.example.test/item", "description": "Summary", "age": "2 hours ago"},
            {"title": "Invalid", "url": "file:///private", "description": "Ignored"},
        ]}}

        def opener(request, *, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps(payload).encode())

        provider = BraveSearchProvider("secret-key", opener=opener)
        self.assertEqual(calls, [])
        result = provider.search("qué pasó hoy", freshness="pd")[0]
        self.assertEqual(result.source, "news.example.test")
        self.assertTrue(result.retrieved_at)
        self.assertEqual(calls[0][0].headers["X-subscription-token"], "secret-key")
        self.assertNotIn("secret-key", repr(result))
        self.assertIn("freshness=pd", calls[0][0].full_url)
        with self.assertRaisesRegex(RuntimeError, "api_key"):
            BraveSearchProvider(None).search("news")

    def test_discovery_falls_back_online_only_when_explicitly_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            discovery = MediaDiscovery(Path(directory), default_roots=[Path(directory) / "missing"])

            class Online:
                available = True
                calls = 0

                def search(self, query, *, limit, quality):
                    self.calls += 1
                    return [MediaSearchResult(id="online:1", provider="online", title=query, stream_url="https://media.example/one.mp3")]

            online = Online()
            discovery.online = online
            self.assertEqual(discovery.search("song", allow_online=False)["results"], [])
            found = discovery.search("song", allow_online=True)
            self.assertTrue(found["online_fallback"])
            self.assertEqual(online.calls, 1)
            self.assertEqual(discovery.resolve("online:1").title, "song")

    def test_search_engine_uses_short_lived_cache(self) -> None:
        class Provider:
            available = True
            calls = 0

            def search(self, query, *, limit, language, freshness):
                self.calls += 1
                from archeon.search.providers import SearchResult

                return [SearchResult(query, "https://example.test", "Summary", "example.test", retrieved_at="now")]

        provider = Provider()
        engine = SearchEngine(provider)
        self.assertEqual(engine.search("Current topic")[0]["title"], "Current topic")
        self.assertEqual(engine.search(" current   topic ")[0]["title"], "Current topic")
        self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
