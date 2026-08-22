from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

from archeon.audio import AudioManager
from archeon.core.events import EventBus
from archeon.voice import VoicePipeline


class VoiceTests(unittest.TestCase):
    def test_wake_name_detection_is_accent_tolerant_and_keeps_multilingual_command(self) -> None:
        self.assertEqual(VoicePipeline.split_wake_command("Archeón, abre Spotify", "Archeon"), "abre spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Arqueón abre Spotify", "Archeon"), "abre spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Nova open Spotify", "Nova"), "open spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Nova ouvre Spotify", "Nova"), "ouvre spotify")
        self.assertIsNone(VoicePipeline.split_wake_command("abre Spotify", "Archeon"))
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

            def configure(self, model_path: Path) -> None:
                self.model_path = model_path

            def unload(self) -> None:
                self.unloaded = True

        class FakeTts:
            name = "fake-tts"

            def __init__(self) -> None:
                self.spoken: tuple[str, str] | None = None

            def speak(self, text: str, stop, *, locale: str = "es", **_settings) -> None:
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

    def test_tts_preview_is_lazy_and_uses_selected_configuration(self) -> None:
        class FakeTts:
            name = "fake-tts"

            def __init__(self) -> None:
                self.call = None

            def speak(self, text, _stop, *, locale="es", **settings) -> None:
                self.call = (text, locale, settings)

        events = EventBus()
        audio = AudioManager(events)
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
            locale_provider=lambda: "fr",
            tts_config_provider=lambda: {"voice_id": "voice-1", "rate": 2, "volume": 70},
        )
        fake_tts = FakeTts()
        pipeline._tts = fake_tts
        self.assertTrue(pipeline.preview("Bonjour"))
        thread = pipeline._thread
        self.assertIsNotNone(thread)
        thread.join(timeout=2.0)
        self.assertEqual(fake_tts.call, ("Bonjour", "fr", {"voice_id": "voice-1", "rate": 2, "volume": 70}))

    def test_barge_in_audio_is_processed_as_a_followup_turn(self) -> None:
        class SequencedStt:
            name = "fake-stt"
            available = True

            def __init__(self) -> None:
                self.values = iter(("primera orden", "segunda orden"))

            def configure(self, _path: Path) -> None:
                pass

            def transcribe(self, _pcm: bytes, _rate: int) -> str:
                return next(self.values)

            def unload(self) -> None:
                pass

        events = EventBus()
        audio = AudioManager(events)
        commands: list[str] = []
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: commands.append(text) or {"ok": True, "message": "respuesta"},
            Path(tempfile.gettempdir()),
        )
        pipeline._stt = SequencedStt()
        pipeline._capture_utterance = lambda: b"first"
        followups = iter((b"second", b""))
        pipeline._speak_with_optional_barge_in = lambda _text, _tts: next(followups)
        audio.start()
        pipeline.start()
        self.assertTrue(pipeline.start_cycle())
        thread = pipeline._thread
        self.assertIsNotNone(thread)
        thread.join(timeout=3.0)
        self.assertEqual(commands, ["primera orden", "segunda orden"])
        pipeline.stop()
        audio.stop()


if __name__ == "__main__":
    unittest.main()
