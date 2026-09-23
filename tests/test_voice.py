from __future__ import annotations

import tempfile
import unittest
import sys
import time
from pathlib import Path
from threading import Event

from archeon.audio import AudioManager
from archeon.core.events import EventBus
from archeon.voice import VoicePipeline
from archeon.voice.catalog import resolve_model


class VoiceTests(unittest.TestCase):
    def test_dictation_repairs_text_without_executing_command(self) -> None:
        class STT:
            def transcribe(self, _pcm: bytes, _sample_rate: int) -> str:
                return "hasme un pe de efe"

            def unload(self) -> None:
                pass

        events = EventBus()
        subscription = events.subscribe("speech.dictation.completed")
        commands: list[str] = []
        pipeline = VoicePipeline(
            events,
            AudioManager(events),
            lambda text: commands.append(text) or {"ok": True},
            Path(tempfile.gettempdir()),
            dictation_repair=lambda _text: "hazme un pdf",
        )
        pipeline._capture_utterance = lambda: b"pcm"  # type: ignore[method-assign]
        pipeline._configure_stt = lambda: None  # type: ignore[method-assign]
        pipeline._stt = STT()  # type: ignore[assignment]
        pipeline.sync_wake_word = lambda: True  # type: ignore[method-assign]

        pipeline._run_dictation()

        event = subscription.get(timeout=0.2)
        self.assertEqual(event.payload["text"], "hazme un pdf")
        self.assertTrue(event.payload["repaired"])
        self.assertEqual(commands, [])
        subscription.close()

    def test_recognition_locale_selects_only_an_installed_sidecar_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            english = root / "vosk-model-small-en-us-0.15"
            english.mkdir()
            spec, path = resolve_model(root, "eco", "en-US")
            self.assertEqual(spec.languages, ("en",))
            self.assertEqual(path, english)
            french_spec, french_path = resolve_model(root, "eco", "fr")
            self.assertEqual(french_spec.languages, ("fr",))
            self.assertFalse(french_path.exists())

    def test_wake_monitor_restarts_after_rapid_disable_enable(self) -> None:
        events = EventBus()
        audio = AudioManager(events)
        enabled = {"value": True}
        pipeline = VoicePipeline(
            events, audio, lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
            wake_enabled_provider=lambda: enabled["value"],
        )
        starts = []
        started = Event()

        def monitor() -> None:
            starts.append(1)
            started.set()
            pipeline._wake_stop.wait()
            pipeline._wake_thread = None

        pipeline._run_wake_monitor = monitor
        audio.start()
        pipeline.start()
        self.assertTrue(started.wait(1.0))
        started.clear()
        enabled["value"] = False
        pipeline.sync_wake_word()
        enabled["value"] = True
        pipeline.sync_wake_word()
        self.assertTrue(started.wait(1.0))
        self.assertEqual(len(starts), 2)
        enabled["value"] = False
        pipeline.stop()
        audio.stop()

    def test_manual_listen_suspends_wake_capture_and_restores_it_after_cycle(self) -> None:
        class FakeStt:
            name = "fake-stt"
            available = True
            loaded = False

            def configure(self, _path: Path) -> None:
                pass

            def transcribe(self, _pcm: bytes, _rate: int) -> str:
                return "estado del sistema"

            def unload(self) -> None:
                pass

        class FakeTts:
            name = "fake-tts"

            def speak(self, *_args, **_kwargs) -> None:
                pass

        events = EventBus()
        audio = AudioManager(events)
        enabled = {"value": True}
        pipeline = VoicePipeline(
            events,
            audio,
            lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()),
            wake_enabled_provider=lambda: enabled["value"],
        )
        pipeline._stt = FakeStt()
        pipeline._tts = FakeTts()
        wake_started = Event()

        def wake_candidate() -> bytes:
            from archeon.audio import AudioMode

            audio.acquire(AudioMode.CAPTURING)
            wake_started.set()
            pipeline._wake_stop.wait(1.0)
            audio.release()
            return b""

        pipeline._wake_candidate = wake_candidate
        pipeline._capture_utterance = lambda: b"manual-pcm"
        audio.start()
        pipeline.start()
        self.assertTrue(wake_started.wait(1.0))
        self.assertTrue(pipeline.start_cycle())
        cycle = pipeline._thread
        self.assertIsNotNone(cycle)
        cycle.join(timeout=2.0)
        self.assertFalse(cycle.is_alive())
        deadline = time.monotonic() + 1.0
        while not pipeline.status()["wake_monitor_active"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(pipeline.status()["wake_monitor_active"])
        enabled["value"] = False
        pipeline.stop()
        audio.stop()

    def test_wake_name_detection_is_accent_tolerant_and_keeps_multilingual_command(self) -> None:
        self.assertEqual(VoicePipeline.split_wake_command("Archeón, abre Spotify", "Archeon"), "abre spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Arqueón abre Spotify", "Archeon"), "abre spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Archi on abre Spotify", "Archeon"), "abre spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Arche on qué hora es", "Archeon"), "que hora es")
        self.assertEqual(VoicePipeline.split_wake_command("Nova open Spotify", "Nova"), "open spotify")
        self.assertEqual(VoicePipeline.split_wake_command("Nova ouvre Spotify", "Nova"), "ouvre spotify")
        self.assertIsNone(VoicePipeline.split_wake_command("abre Spotify", "Archeon"))
        self.assertIsNone(VoicePipeline.split_wake_command("archivo abre Spotify", "Archeon"))

    def test_wake_command_is_blocked_when_speaker_is_not_authorized(self) -> None:
        class FakeStt:
            def transcribe(self, _pcm, _rate): return "Archeon abre notas"
            def unload(self): pass
            def configure(self, _path): pass

        class RejectingVerifier:
            def public_profiles(self): return [{"id": "owner", "name": "Propietario", "enabled": True}]
            def verify(self, _pcm): return {"authorized": False, "confidence": 0.41, "profile_id": None}

        events = EventBus()
        enabled = {"value": True}
        commands = []
        rejected = events.subscribe("wake.speaker.rejected")
        pipeline = VoicePipeline(
            events, AudioManager(events), lambda text: commands.append(text) or {"ok": True},
            Path(tempfile.gettempdir()), wake_enabled_provider=lambda: enabled["value"],
            speaker_verifier=RejectingVerifier(), speaker_verification_enabled_provider=lambda: True,
        )
        pipeline._stt = FakeStt()
        pipeline._configure_stt = lambda: None
        pipeline._wake_candidate = lambda: enabled.update(value=False) or b"candidate-pcm"
        pipeline._run_wake_monitor()
        self.assertEqual(commands, [])
        self.assertFalse(rejected.get(timeout=0.2).payload["authorized"])
        rejected.close()

    def test_wake_diagnostics_are_exposed_without_persisting_audio(self) -> None:
        events = EventBus()
        pipeline = VoicePipeline(
            events, AudioManager(events), lambda text: {"ok": True, "message": text},
            Path(tempfile.gettempdir()) / "missing-archeon-model",
        )
        status = pipeline.status()
        self.assertFalse(status["wake_stream_active"])
        self.assertEqual(status["wake_frames_received"], 0)
        self.assertIsNone(status["wake_last_candidate"])
        self.assertNotIn("pcm", status)
        self.assertEqual(status["wake_target_sample_rate"], 16_000)
        self.assertIn("WASAPI", status["wake_backend"])
        self.assertIn("wake_worker_status", status)

    def test_wake_failures_are_classified_for_advanced_diagnostics(self) -> None:
        self.assertEqual(
            VoicePipeline._classify_wake_error(FileNotFoundError("model missing")),
            "model_missing",
        )
        self.assertEqual(
            VoicePipeline._classify_wake_error(RuntimeError("audio session already active")),
            "audio_device_busy",
        )
        self.assertEqual(
            VoicePipeline._classify_wake_error(RuntimeError("invalid input device")),
            "audio_device_unavailable",
        )

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
