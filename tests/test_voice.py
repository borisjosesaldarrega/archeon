from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

from archeon.audio import AudioManager
from archeon.core.events import EventBus
from archeon.voice import VoicePipeline


class VoiceTests(unittest.TestCase):
    def test_audio_and_model_dependencies_stay_lazy_at_idle(self) -> None:
        events = EventBus()
        audio = AudioManager(events)
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
        )
        audio.start()
        pipeline.start()
        self.assertNotIn("sounddevice", sys.modules)
        self.assertNotIn("vosk", sys.modules)
        self.assertNotIn("comtypes", sys.modules)
        pipeline.stop()
        audio.stop()

    def test_cycle_connects_transcription_command_and_speech(self) -> None:
        class FakeStt:
            name = "fake-stt"
            available = True

            def __init__(self) -> None:
                self.unloaded = False

            def transcribe(self, pcm: bytes, sample_rate: int) -> str:
                self.asserted = (pcm, sample_rate)
                return "estado del sistema"

            def unload(self) -> None:
                self.unloaded = True

        class FakeTts:
            name = "fake-tts"

            def __init__(self) -> None:
                self.spoken: tuple[str, str] | None = None

            def speak(self, text: str, stop, *, locale: str = "es") -> None:
                self.spoken = (text, locale)

        events = EventBus()
        audio = AudioManager(events)
        commands: list[str] = []
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: commands.append(text) or {"ok": True, "message": "Todo correcto"},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
            locale_provider=lambda: "es",
        )
        fake_stt = FakeStt()
        fake_tts = FakeTts()
        pipeline._stt = fake_stt
        pipeline._tts = fake_tts
        pipeline._capture_utterance = lambda: b"real-pcm"
        audio.start()
        pipeline.start()
        self.assertTrue(pipeline.start_cycle())
        thread = pipeline._thread
        self.assertIsNotNone(thread)
        thread.join(timeout=3.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(commands, ["estado del sistema"])
        self.assertEqual(fake_tts.spoken, ("Todo correcto", "es"))
        self.assertTrue(fake_stt.unloaded)
        pipeline.stop()
        audio.stop()

    def test_missing_model_keeps_voice_honestly_unavailable(self) -> None:
        events = EventBus()
        audio = AudioManager(events)
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
        )
        audio.start()
        pipeline.start()
        self.assertFalse(pipeline.status()["available"])
        self.assertFalse(pipeline.start_cycle())
        pipeline.stop()
        audio.stop()


if __name__ == "__main__":
    unittest.main()
