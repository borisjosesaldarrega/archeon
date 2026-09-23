from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from archeon.media.discovery import MediaDiscovery
from archeon.media.providers import MediaSearchResult
from archeon.media.providers import AudiusMediaProvider, JamendoMediaProvider, LocalMediaProvider, YouTubeVisualProvider
from archeon.search.engine import SearchEngine
from archeon.search.providers import BraveSearchProvider, GoogleNewsRssProvider


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

    def test_audius_provider_returns_only_ungated_official_streams(self) -> None:
        payload = {"data": [
            {"id": "track1", "title": "Julieta remix", "duration": 161, "is_stream_gated": False,
             "permalink": "/artist/julieta", "user": {"name": "Artist"},
             "artwork": {"480x480": "https://api.audius.co/art.jpg"}},
            {"id": "gated", "title": "Private", "is_stream_gated": True},
        ]}

        def opener(_request, *, timeout):
            self.assertEqual(timeout, 8)
            return io.BytesIO(json.dumps(payload).encode())

        result = AudiusMediaProvider(opener=opener).search("julieta")[0]
        self.assertEqual(result.provider, "audius")
        self.assertEqual(result.artist, "Artist")
        self.assertEqual(result.duration_ms, 161_000)
        self.assertEqual(result.stream_url, "https://api.audius.co/v1/tracks/track1/stream?app_name=ARCHEON")
        self.assertEqual(result.source_url, "https://audius.co/artist/julieta")

    def test_youtube_provider_returns_metadata_for_official_visible_player_only(self) -> None:
        payload = {"items": [{
            "id": {"videoId": "abcDEF_1234"},
            "snippet": {"title": "Canción oficial", "channelTitle": "Canal del artista",
                        "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/abcDEF_1234/hqdefault.jpg"}}},
        }]}
        calls = []

        def opener(request, *, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps(payload).encode())

        provider = YouTubeVisualProvider("private-api-key", opener=opener)
        result = provider.search("canción artista")[0]
        self.assertEqual(result.provider, "youtube_visual")
        self.assertEqual(result.playback_kind, "official_web")
        self.assertEqual(result.external_id, "abcDEF_1234")
        self.assertIsNone(result.stream_url)
        self.assertEqual(result.source_url, "https://www.youtube.com/watch?v=abcDEF_1234")
        self.assertIn("videoEmbeddable=true", calls[0][0].full_url)
        self.assertIn("type=video", calls[0][0].full_url)
        self.assertNotIn("private-api-key", repr(result))

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

    def test_keyless_news_provider_is_lazy_and_returns_cited_rss_results(self) -> None:
        calls = []
        payload = b'''<?xml version="1.0"?><rss><channel><item><title>Actualidad</title><link>https://news.google.com/rss/articles/one</link><description>&lt;b&gt;Resumen&lt;/b&gt;</description><pubDate>Sun, 23 Aug 2026 10:00:00 GMT</pubDate><source url="https://example.test">Fuente</source></item></channel></rss>'''

        def opener(request, *, timeout):
            calls.append((request, timeout))
            return io.BytesIO(payload)

        provider = GoogleNewsRssProvider(opener=opener)
        self.assertEqual(calls, [])
        result = provider.search("noticias de hoy", language="es")[0]
        self.assertEqual(result.title, "Actualidad")
        self.assertEqual(result.source, "Fuente")
        self.assertEqual(result.description, "Resumen")
        self.assertTrue(result.retrieved_at)
        self.assertEqual(calls[0][1], 8)

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

    def test_discovery_aggregates_providers_and_survives_one_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            discovery = MediaDiscovery(Path(directory), default_roots=[Path(directory) / "missing"])

            class Failed:
                name = "failed"
                available = True
                def search(self, *_args, **_kwargs):
                    raise RuntimeError("offline")

            class Working:
                name = "working"
                available = True
                def search(self, query, **_kwargs):
                    return [MediaSearchResult(id="working:1", provider="working", title=query, stream_url="https://media.example/song.mp3")]

            discovery.online = Failed()
            discovery.register_online_provider(Working())
            found = discovery.search("original song", allow_online=True)
            self.assertEqual(found["results"][0]["id"], "working:1")
            self.assertEqual(found["provider_errors"], ["failed:RuntimeError"])

    def test_exhaustive_discovery_keeps_local_and_online_candidates_for_global_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music = root / "Music"
            music.mkdir()
            (music / "Julieta remix.mp3").write_bytes(b"candidate-only")
            discovery = MediaDiscovery(root, default_roots=[music])
            discovery.refresh()

            class Online:
                name = "online"
                available = True
                calls = 0

                def search(self, _query, **_kwargs):
                    self.calls += 1
                    return [MediaSearchResult(
                        id="online:original", provider="online", title="Julieta",
                        artist="Latin Mafia", stream_url="https://media.example/original.mp3",
                    )]

            online = Online()
            discovery.online = online
            local_only = discovery.search("julieta", allow_online=True)
            self.assertEqual(online.calls, 0)
            self.assertEqual([item["provider"] for item in local_only["results"]], ["local"])

            exhaustive = discovery.search(
                "julieta", allow_online=True, include_online_with_local=True,
            )
            self.assertEqual(online.calls, 1)
            self.assertEqual(
                {item["provider"] for item in exhaustive["results"]}, {"local", "online"},
            )

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
