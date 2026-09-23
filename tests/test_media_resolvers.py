from __future__ import annotations

import unittest

from archeon.media.matcher import MediaSearchQuery, rank_candidates
from archeon.media.resolvers import LegacyLocalResolver, YtDlpAuthorizedResolver


class _FakeYdl:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, source, *, download):
        assert source == "https://media.owner.example/library/song"
        assert download is False
        return {
            "id": "owned-1", "title": "Owned song", "artist": "Owner", "duration": 123,
            "thumbnail": "https://cdn.owner.example/cover.jpg",
            "formats": [
                {"url": "https://cdn.owner.example/video-only", "acodec": "none"},
                {"url": "https://cdn.owner.example/audio.mp3", "acodec": "mp3", "protocol": "https"},
            ],
        }


class AuthorizedResolverTests(unittest.TestCase):
    def test_authorized_source_is_resolved_lazily_without_download(self) -> None:
        resolver = YtDlpAuthorizedResolver(("owner.example",), ydl_factory=_FakeYdl)
        result = resolver.resolve("https://media.owner.example/library/song")
        self.assertEqual(result.provider, "yt_dlp_authorized")
        self.assertEqual(result.stream_url, "https://cdn.owner.example/audio.mp3")
        self.assertEqual(result.duration_ms, 123_000)

    def test_non_allowlisted_and_youtube_sources_are_rejected(self) -> None:
        resolver = YtDlpAuthorizedResolver(("owner.example", "youtube.com"), ydl_factory=_FakeYdl)
        with self.assertRaisesRegex(ValueError, "not_authorized"):
            resolver.resolve("https://untrusted.example/song")
        with self.assertRaisesRegex(ValueError, "official_visible_player"):
            resolver.resolve("https://www.youtube.com/watch?v=abc123")


class _FakeLegacyYdl:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, source, *, download):
        assert download is False
        if source.startswith("ytsearch"):
            return {"entries": [
                {"id": "remix", "title": "Limón y Sal (SAU Remix)", "channel": "SAU", "duration": 180},
                {"id": "original", "title": "Julieta Venegas - Limón y Sal (Video Oficial)",
                 "channel": "Julieta Venegas", "channel_is_verified": True, "duration": 207},
                {"id": "live", "title": "Limón y Sal en vivo", "channel": "Julieta Venegas", "duration": 230},
            ]}
        assert source.endswith("watch?v=original")
        return {
            "id": "original", "title": "Julieta Venegas - Limón y Sal (Video Oficial)",
            "artist": "Julieta Venegas", "duration": 207,
            "webpage_url": source, "thumbnail": "https://i.example/original.jpg",
            "formats": [{"url": "https://media.example/original.webm", "acodec": "opus", "protocol": "https"}],
        }


class LegacyLocalResolverTests(unittest.TestCase):
    def test_multiple_candidates_are_ranked_original_first_then_resolved(self) -> None:
        resolver = LegacyLocalResolver(ydl_factory=_FakeLegacyYdl)
        candidates = resolver.search("limon y sal julieta venegas", limit=8)
        self.assertEqual(len(candidates), 3)
        query = MediaSearchQuery(title="limon y sal", artist="julieta venegas")
        ranked = rank_candidates(query, candidates)
        self.assertEqual(ranked[0].candidate.external_id, "original")
        result = resolver.resolve(ranked[0].candidate)
        self.assertEqual(result.stream_url, "https://media.example/original.webm")
        self.assertEqual(result.playback_kind, "native_audio")

    def test_status_is_integrated_and_requires_no_api_key(self) -> None:
        resolver = LegacyLocalResolver(ydl_factory=_FakeLegacyYdl)
        status = resolver.status(developer=True)
        self.assertTrue(status["available"])
        self.assertTrue(status["enabled"])
        self.assertFalse(status["api_key_required"])
        self.assertEqual(status["idle_processes"], 0)


if __name__ == "__main__":
    unittest.main()
