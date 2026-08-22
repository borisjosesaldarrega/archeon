from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from archeon.media.backend import BufferedHttpSource
from archeon.ui.server import UI_ROOT


class Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Type": "audio/mpeg"}


class StreamingSourceTests(unittest.TestCase):
    def test_bounded_https_source_feeds_miniaudio_without_temp_file(self) -> None:
        encoded = (UI_ROOT / "archeon-audio.mp3").read_bytes()
        with patch("archeon.media.backend.urllib.request.urlopen", return_value=Response(encoded)):
            source = BufferedHttpSource("https://prod-1.storage.jamendo.com/track.mp3")
            self.assertEqual(source.content_type, "audio/mpeg")
            self.assertLessEqual(len(source._buffer), source.BUFFER_SIZE + source.BLOCK_SIZE)
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


if __name__ == "__main__":
    unittest.main()
