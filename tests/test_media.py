from __future__ import annotations

import tempfile
import time
import unittest
import sys
import json
import subprocess
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
        self.on_progress = None
        self.__class__.instances.append(self)

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def open(self, path: str, *, seek_ms: int, on_end, on_progress=None) -> None:
        self.path = path
        self.position_ms = seek_ms
        self.on_end = on_end
        self.on_progress = on_progress

    def play(self) -> None:
        self.playing = True
        self.position_ms += 20
        if self.on_progress is not None:
            self.on_progress(self.position_ms)

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
        # This contract must be checked in a clean interpreter. In the full
        # suite another playback test may legitimately have imported these
        # process-global modules already.
        script = """
import json, sys, tempfile
from pathlib import Path
from archeon.core.events import EventBus
from archeon.media import MediaEngine
with tempfile.TemporaryDirectory() as root:
    events = EventBus(); media = MediaEngine(events, Path(root)); media.start()
    print(json.dumps({"miniaudio": "miniaudio" in sys.modules, "tinytag": "tinytag" in sys.modules, "backend": media.backend_loaded}))
    media.stop(); events.close()
"""
        idle = json.loads(subprocess.check_output([sys.executable, "-c", script], text=True))
        self.assertFalse(idle["miniaudio"])
        self.assertFalse(idle["tinytag"])
        self.assertFalse(idle["backend"])
        self.assertFalse(self.media.backend_loaded)
        self.assertEqual(self.media.status()["state"], "stopped")

    def test_queue_controls_seek_volume_and_release(self) -> None:
        tracks = self.media.load([self.track, self.track])
        self.assertEqual(len(tracks), 2)
        self.media.play()
        self.assertEqual(self.media.state, MediaState.PLAYING)
        self.assertEqual(FakePlayer.instances[-1].output_device_id, "2")
        active_player = FakePlayer.instances[-1]
        active_position = active_player.position_ms
        self.media.play()
        self.assertIs(FakePlayer.instances[-1], active_player)
        self.assertEqual(active_player.position_ms, active_position)
        self.media.pause()
        self.assertEqual(self.media.state, MediaState.PAUSED)
        paused_position = active_player.position_ms
        self.media.resume()
        self.assertIs(FakePlayer.instances[-1], active_player)
        self.assertGreater(active_player.position_ms, paused_position)
        self.media.seek(1000)
        self.assertGreaterEqual(self.media.status()["position_ms"], 1000)
        self.assertTrue(self.media.status()["playback_evidence"]["verified_playing"])
        self.assertTrue(self.media.status()["playback_evidence"]["frames_advancing"])
        self.media._last_progress_at -= 6.0
        self.assertFalse(self.media.status()["playback_evidence"]["verified_playing"])
        current_player = FakePlayer.instances[-1]
        current_player.position_ms += 20
        current_player.on_progress(current_player.position_ms)
        self.assertTrue(self.media.status()["playback_evidence"]["verified_playing"])
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
        self.assertTrue(str(tracks[0]["artwork_url"]).startswith("/media/art/remote-"))
        self.media.play()
        self.assertEqual(FakePlayer.instances[-1].path, result.stream_url)
        with self.assertRaisesRegex(RuntimeError, "seek_unavailable"):
            self.media.seek(1000)

    def test_official_web_result_never_enters_native_decoder_and_requires_clock_evidence(self) -> None:
        result = MediaSearchResult(
            id="youtube_visual:abc123XYZ", provider="youtube_visual",
            title="Official video", artist="Artist",
            source_url="https://www.youtube.com/watch?v=abc123XYZ",
            artwork_url="https://i.ytimg.com/vi/abc123XYZ/hqdefault.jpg",
            playback_kind="official_web", external_id="abc123XYZ",
        )
        requested = self.events.subscribe("music.web.requested")
        self.media.load_results([result])
        status = self.media.play()
        self.assertEqual(status["state"], "buffering")
        self.assertFalse(status["backend_loaded"])
        self.assertFalse(status["playback_evidence"]["verified_playing"])
        self.assertEqual(requested.get(timeout=0.2).payload["external_id"], "abc123XYZ")
        status = self.media.report_web_state("playing", 0, 180_000)
        self.assertEqual(status["state"], "buffering")
        status = self.media.report_web_state("playing", 600, 180_000)
        self.assertEqual(status["state"], "playing")
        self.assertTrue(status["playback_evidence"]["verified_playing"])
        self.assertFalse(self.media.backend_loaded)
        self.media.stop_playback()
        self.assertEqual(self.media.status()["state"], "stopped")
        requested.close()

    def test_dj_continues_three_tracks_and_excludes_history(self) -> None:
        self.media.stop()
        generated: list[tuple[str, ...]] = []

        def continuation(_current, excluded, _strategy):
            generated.append(excluded)
            number = len(generated) + 1
            return MediaSearchResult(
                id=f"jamendo:{number}", provider="jamendo", title=f"Track {number}",
                artist="Artist", stream_url=f"https://media.example/{number}.mp3",
            )

        self.media = MediaEngine(
            self.events, Path(self.temp.name), player_factory=FakePlayer,
            dj_enabled_provider=lambda: True, continuation_provider=continuation,
        )
        self.media.start()
        self.media.load_results([MediaSearchResult(
            id="jamendo:1", provider="jamendo", title="Track 1", artist="Artist",
            stream_url="https://media.example/1.mp3",
        )])
        self.media.play()
        for expected in (2, 3):
            FakePlayer.instances[-1].on_end()
            deadline = time.monotonic() + 1
            while self.media.current and self.media.current.id != f"jamendo:{expected}" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.media.current.id, f"jamendo:{expected}")
        self.assertIn("jamendo:1", generated[0])
        self.assertIn("jamendo:2", generated[1])
        self.assertEqual(self.media.state, MediaState.PLAYING)

    def test_user_stop_blocks_dj_restart_and_rejection_is_recorded(self) -> None:
        self.media.reject("jamendo:rejected")
        self.media.load([self.track])
        self.media.play()
        ended = FakePlayer.instances[-1].on_end
        self.media.stop_playback()
        ended()
        time.sleep(0.03)
        status = self.media.status()
        self.assertEqual(status["state"], "stopped")
        self.assertIn("jamendo:rejected", status["rejected"])


if __name__ == "__main__":
    unittest.main()
