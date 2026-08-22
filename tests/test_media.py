from __future__ import annotations

import tempfile
import time
import unittest
import sys
from pathlib import Path

from archeon.core.events import EventBus
from archeon.media import MediaEngine, MediaState
from archeon.media.providers import MediaSearchResult
from archeon.ui.server import UI_ROOT


class FakePlayer:
    instances: list["FakePlayer"] = []

    def __init__(self, *, output_device_id=None) -> None:
        self.output_device_id = output_device_id
        self.position_ms = 0
        self.playing = False
        self.closed = False
        self.volume = 0.0
        self.on_end = None
        self.__class__.instances.append(self)

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def open(self, path: str, *, seek_ms: int, on_end) -> None:
        self.path = path
        self.position_ms = seek_ms
        self.on_end = on_end

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def close(self) -> None:
        self.playing = False
        self.closed = True


class MediaEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        FakePlayer.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.events = EventBus()
        self.media = MediaEngine(
            self.events,
            Path(self.temp.name),
            output_device_provider=lambda: "2",
            player_factory=FakePlayer,
        )
        self.media.start()
        self.track = UI_ROOT / "archeon-audio.mp3"

    def tearDown(self) -> None:
        self.media.stop()
        self.events.close()
        self.temp.cleanup()

    def test_dependencies_and_backend_stay_unloaded_at_idle(self) -> None:
        self.assertNotIn("miniaudio", sys.modules)
        self.assertNotIn("tinytag", sys.modules)
        self.assertFalse(self.media.backend_loaded)

    def test_queue_controls_seek_volume_and_release(self) -> None:
        tracks = self.media.load([self.track, self.track])
        self.assertEqual(len(tracks), 2)
        self.media.play()
        self.assertEqual(self.media.state, MediaState.PLAYING)
        self.assertEqual(FakePlayer.instances[-1].output_device_id, "2")
        self.media.pause()
        self.assertEqual(self.media.state, MediaState.PAUSED)
        self.media.resume()
        self.media.seek(1000)
        self.assertEqual(self.media.status()["position_ms"], 1000)
        self.media.set_volume(0.25)
        self.assertEqual(FakePlayer.instances[-1].volume, 0.25)
        self.media.next()
        self.assertEqual(self.media.status()["queue_index"], 1)
        self.media.previous()
        self.assertEqual(self.media.status()["queue_index"], 0)
        self.media.stop_playback()
        self.assertEqual(self.media.state, MediaState.STOPPED)
        self.assertFalse(self.media.backend_loaded)
        self.assertTrue(all(player.closed for player in FakePlayer.instances))

    def test_track_end_advances_queue_without_polling(self) -> None:
        self.media.load([self.track, self.track])
        self.media.play()
        FakePlayer.instances[-1].on_end()
        deadline = time.monotonic() + 1.0
        while self.media.status()["queue_index"] != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.media.status()["queue_index"], 1)

    def test_online_result_uses_same_queue_without_loading_at_idle(self) -> None:
        result = MediaSearchResult(
            id="jamendo:12", provider="jamendo", title="Online track", artist="Artist",
            stream_url="https://prod-1.storage.jamendo.com/track.mp3",
            artwork_url="https://usercontent.jamendo.com/cover.jpg",
            source_url="https://www.jamendo.com/track/12",
        )
        tracks = self.media.load_results([result])
        self.assertEqual(tracks[0]["provider"], "jamendo")
        self.media.play()
        self.assertEqual(FakePlayer.instances[-1].path, result.stream_url)
        with self.assertRaisesRegex(RuntimeError, "seek_unavailable"):
            self.media.seek(1000)


if __name__ == "__main__":
    unittest.main()
