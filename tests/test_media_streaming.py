from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from archeon.media.backend import BufferedHttpSource, is_online_media_path
from archeon.media.codecs import CodecBackend, CodecRouter, FFmpegProvider
from archeon.media.metadata import MetadataReader
from archeon.ui.server import UI_ROOT


class Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Type": "audio/mpeg"}


class ImageResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self.headers = {"Content-Type": "image/png"}
        self._url = url

    def geturl(self) -> str:
        return self._url


class StreamingSourceTests(unittest.TestCase):
    def test_ffmpeg_is_optional_not_a_mandatory_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = (root / "pyproject.toml").read_text(encoding="utf-8").casefold()
        self.assertNotIn("ffmpeg", manifest)
        self.assertNotIn("imageio-ffmpeg", manifest)

    def test_codec_router_separates_youtube_provider_from_decoders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            router = CodecRouter(Path(temporary))
            decision = router.select("https://youtube.com/watch?v=abc", provider="youtube_visual")
            self.assertEqual(decision.backend, CodecBackend.OFFICIAL_WEB)
            self.assertEqual(decision.reason, "official_player_required")
            with self.assertRaisesRegex(RuntimeError, "official_web_player_required"):
                router.create_player(
                    "https://youtube.com/watch?v=abc", provider="youtube_visual", output_device_id=None,
                )

    def test_codec_router_prefers_light_backend_and_ffmpeg_only_for_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ffmpeg.exe"
            executable.touch()
            optional = FFmpegProvider(Path(temporary), executable=executable)
            router = CodecRouter(Path(temporary), ffmpeg=optional)
            self.assertEqual(router.select("song.mp3").backend, CodecBackend.MINIAUDIO)
            m4a = router.select("song.m4a")
            self.assertEqual(m4a.backend, CodecBackend.MEDIA_FOUNDATION)
            self.assertFalse(m4a.available)
            self.assertEqual(m4a.fallback, CodecBackend.FFMPEG_OPTIONAL)
            self.assertEqual(router.select("song.webm").backend, CodecBackend.FFMPEG_OPTIONAL)
            remote = router.select("https://prod-1.storage.jamendo.com/track.mp3", provider="jamendo")
            self.assertEqual(remote.backend, CodecBackend.FFMPEG_OPTIONAL)
            self.assertEqual(remote.fallback, CodecBackend.MINIAUDIO)
            self.assertEqual(remote.reason, "authorized_remote_stream_with_reconnect")

    def test_ffmpeg_remote_stream_requires_authorized_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ffmpeg.exe"
            executable.touch()
            provider = FFmpegProvider(Path(temporary), executable=executable)
            player = provider.create_player(output_device_id=None, provider="youtube_visual")
            with self.assertRaisesRegex(RuntimeError, "remote_media_not_authorized"):
                player.open("https://youtube.com/audio", on_end=lambda: None)

    def test_bounded_https_source_feeds_miniaudio_without_temp_file(self) -> None:
        encoded = (UI_ROOT / "archeon-audio.mp3").read_bytes()
        with patch("archeon.media.backend.urllib.request.urlopen", return_value=Response(encoded)):
            source = BufferedHttpSource("https://prod-1.storage.jamendo.com/track.mp3")
            self.assertEqual(source.content_type, "audio/mpeg")
            self.assertLessEqual(len(source._buffer), source.BUFFER_SIZE + source.BLOCK_SIZE)
            self.assertEqual(source.BUFFER_SIZE, 256 * 1024)
            import miniaudio

            stream = miniaudio.stream_any(source, source_format=miniaudio.FileFormat.MP3)
            samples = next(stream)
            self.assertGreater(len(samples), 0)
            stream.close()
            source.close()
            self.assertFalse(source._thread.is_alive())

    def test_online_source_rejects_insecure_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_online_media_url"):
            BufferedHttpSource("http://example.test/audio.mp3")

    def test_windows_drive_path_is_local_not_an_url_scheme(self) -> None:
        self.assertFalse(is_online_media_path(r"C:\Users\Persona\Music\song.mp3"))
        self.assertTrue(is_online_media_path("https://media.example/song.mp3"))

    def test_remote_cover_is_proxied_once_and_cached_for_ui_and_ghost(self) -> None:
        cover_url = "https://images.example.test/cover.png"
        encoded = (UI_ROOT / "logo_asitente.png").read_bytes()
        opener = Mock(return_value=ImageResponse(encoded, cover_url))
        with tempfile.TemporaryDirectory() as temporary:
            reader = MetadataReader(Path(temporary), opener=opener)
            artwork_id = reader.register_remote_artwork(cover_url)
            self.assertTrue(str(artwork_id).startswith("remote-"))
            first = reader.artwork(str(artwork_id))
            second = reader.artwork(str(artwork_id))
        self.assertEqual(first, ("image/png", encoded))
        self.assertEqual(second, first)
        opener.assert_called_once()

    def test_remote_cover_rejects_local_or_insecure_urls(self) -> None:
        reader = MetadataReader(Path("unused"))
        self.assertIsNone(reader.register_remote_artwork("http://images.example/cover.jpg"))
        self.assertIsNone(reader.register_remote_artwork("https://127.0.0.1/cover.jpg"))


if __name__ == "__main__":
    unittest.main()
