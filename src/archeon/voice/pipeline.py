"""One-shot microphone → VAD → STT → assistant → TTS pipeline."""

from __future__ import annotations

import importlib.util
import math
import time
from array import array
from collections import deque
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any

from archeon.audio import AudioManager, AudioMode, AudioSessionConfig
from archeon.audio.wasapi import WasapiSharedCapture
from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent

from .providers import SapiTextToSpeech, VoskSpeechToText
from .catalog import PROFILES, resolve_model, resolve_profile


class VoicePipeline(ManagedComponent):
    SAMPLE_RATE = 16_000
    FRAME_MS = 20

    def __init__(
        self,
        events: EventBus,
        audio: AudioManager,
        command_handler: Callable[[str], dict[str, Any]],
        models_root: Path,
        *,
        input_device_id: str | None = None,
        input_device_provider: Callable[[], str | None] | None = None,
        locale_provider: Callable[[], str] | None = None,
        profile_provider: Callable[[], str] | None = None,
        tts_config_provider: Callable[[], dict[str, Any]] | None = None,
        barge_in_provider: Callable[[], bool] | None = None,
        wake_enabled_provider: Callable[[], bool] | None = None,
        wake_name_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__("voice")
        self._events = events
        self._audio = audio
        self._command_handler = command_handler
        self._models_root = models_root
        self._profile_provider = profile_provider or (lambda: "eco")
        _, model_path = resolve_model(models_root, self._profile_provider())
        self._stt = VoskSpeechToText(model_path)
        self._tts = SapiTextToSpeech()
        self._input_device_id = input_device_id
        self._input_device_provider = input_device_provider
        self._locale_provider = locale_provider or (lambda: "es")
        self._tts_config_provider = tts_config_provider or (lambda: {})
        self._barge_in_provider = barge_in_provider or (lambda: False)
        self._wake_enabled_provider = wake_enabled_provider or (lambda: False)
        self._wake_name_provider = wake_name_provider or (lambda: "Archeon")
        self._stop_event = Event()
        self._tts_stop_event = Event()
        self._barge_monitor_stop = Event()
        self._thread: Thread | None = None
        self._wake_thread: Thread | None = None
        self._wake_stop = Event()
        self._lock = RLock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def status(self) -> dict[str, Any]:
        profile = resolve_profile(self._profile_provider())
        model, model_path = resolve_model(self._models_root, profile.name)
        self._stt.configure(model_path)
        dependencies = all(
            importlib.util.find_spec(name) is not None
            for name in ("sounddevice", "webrtcvad", "vosk", "comtypes")
        )
        return {
            "available": dependencies and self._stt.available,
            "busy": self.busy,
            "stt": self._stt.name,
            "tts": self._tts.name,
            "model_installed": self._stt.available,
            "capture": "WASAPI shared",
            "profile": profile.name,
            "model_id": model.id,
            "languages": list(model.languages),
            "wake_word_enabled": self._wake_enabled_provider(),
            "wake_name": self._wake_name_provider(),
            "wake_monitor_active": bool(self._wake_thread and self._wake_thread.is_alive()),
        }

    def sync_wake_word(self) -> None:
        thread = self._wake_thread
        if self._wake_enabled_provider() and (thread is None or not thread.is_alive()):
            self._wake_stop.clear()
            self._wake_thread = Thread(target=self._run_wake_monitor, name="archeon-wake-word", daemon=False)
            self._wake_thread.start()
        elif not self._wake_enabled_provider() and thread is not None:
            self._wake_stop.set()

    @classmethod
    def split_wake_command(cls, text: str, wake_name: str) -> str | None:
        from difflib import SequenceMatcher
        words = cls._normalize_wake_text(text).split()
        wake_words = cls._normalize_wake_text(wake_name).split()
        if not wake_words or len(words) < len(wake_words):
            return None
        for start in range(min(2, len(words) - len(wake_words) + 1)):
            candidate = " ".join(words[start:start + len(wake_words)])
            expected = " ".join(wake_words)
            product_alias = expected == "archeon" and candidate in {"arqueon", "archon"}
            if candidate == expected or product_alias or (len(expected) >= 4 and SequenceMatcher(None, candidate, expected).ratio() >= 0.82):
                return " ".join(words[start + len(wake_words):])
        return None

    @staticmethod
    def _normalize_wake_text(text: str) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKD", text.casefold())
        return " ".join("".join(c for c in value if c.isalnum() or c.isspace()).split())

    def _wake_candidate(self) -> bytes:
        import webrtcvad
        vad = webrtcvad.Vad(3)
        frames: list[bytes] = []
        pre_roll: deque[bytes] = deque(maxlen=12)
        recent: deque[bool] = deque(maxlen=5)
        started = False
        silence = total = 0
        backend = self._audio.acquire(AudioMode.CAPTURING, config=AudioSessionConfig(
            sample_rate=self.SAMPLE_RATE, channels=1, block_ms=self.FRAME_MS,
            input_device_id=(self._input_device_provider() if self._input_device_provider else self._input_device_id),
        ))
        if not isinstance(backend, WasapiSharedCapture):
            raise RuntimeError("invalid capture backend")
        def consume(chunk: bytes) -> bool:
            nonlocal started, silence, total
            total += 1
            voiced = vad.is_speech(chunk, self.SAMPLE_RATE)
            recent.append(voiced)
            if not started:
                pre_roll.append(chunk)
                if len(recent) == 5 and sum(recent) >= 4:
                    started = True
                    frames.extend(pre_roll)
                return True
            frames.append(chunk)
            silence = silence + 1 if not voiced else 0
            return silence < 30 and len(frames) < 250
        try:
            backend.capture(self._wake_stop, consume)
        finally:
            self._audio.release()
        return b"".join(frames)

    def _run_wake_monitor(self) -> None:
        rejected = 0
        try:
            while not self._wake_stop.is_set() and self._wake_enabled_provider():
                if self.busy:
                    self._wake_stop.wait(0.25)
                    continue
                try:
                    pcm = self._wake_candidate()
                    if not pcm or self._wake_stop.is_set():
                        continue
                    text = self._stt.transcribe(pcm, self.SAMPLE_RATE)
                except (OSError, RuntimeError) as error:
                    self._events.publish("wake.monitor.error", {"error": str(error)}, source="wake")
                    self._wake_stop.wait(1.0)
                    continue
                finally:
                    self._stt.unload()
                command = self.split_wake_command(text, self._wake_name_provider())
                if command is None:
                    rejected += 1
                    self._events.publish("wake.candidate.rejected", {"count": rejected}, source="wake")
                    continue
                self._events.publish("wake.detected", {"wake_name": self._wake_name_provider(), "command": command}, source="wake")
                if command:
                    self._run_wake_command(command)
                else:
                    self.start_cycle()
        finally:
            self._stt.unload()
            self._wake_thread = None

    def _run_wake_command(self, text: str) -> None:
        with self._lock:
            if self._busy:
                return
            self._busy = True
        try:
            self._events.publish("assistant.processing.started", {"text": text, "wake_word": True}, source="voice")
            response = self._command_handler(text)
            self._events.publish("assistant.processing.completed", response, source="voice")
            spoken = str(response.get("message", ""))
            if response.get("ok") and spoken:
                self._events.publish("assistant.speaking.started", {"text": spoken}, source="voice")
                self._tts.speak(spoken, self._tts_stop_event, locale=self._locale_provider(), **self._tts_config_provider())
                self._events.publish("assistant.speaking.ended", source="voice")
        except Exception as error:
            self._events.publish("voice.cycle.error", {"error": str(error)}, source="voice")
        finally:
            with self._lock:
                self._busy = False

    def devices(self) -> list[dict[str, Any]]:
        return WasapiSharedCapture.devices()

    def catalog(self) -> dict[str, Any]:
        return {
            "profiles": list(PROFILES),
            "input_devices": self.devices(),
            "tts_voices": self._tts.voices(),
            "tts_outputs": self._tts.outputs(),
            "status": self.status(),
        }

    def start_cycle(self) -> bool:
        with self._lock:
            if self._busy or not self.status()["available"]:
                return False
            self._busy = True
            self._stop_event.clear()
            self._tts_stop_event.clear()
            self._barge_monitor_stop.clear()
            self._thread = Thread(target=self._run_cycle, name="archeon-voice-cycle", daemon=False)
            self._thread.start()
            return True

    def interrupt(self) -> None:
        self._stop_event.set()
        self._tts_stop_event.set()
        self._barge_monitor_stop.set()

    def preview(self, text: str) -> bool:
        preview_text = text.strip()[:240]
        if not preview_text:
            raise ValueError("empty_tts_preview")
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._tts_stop_event.clear()
            self._thread = Thread(
                target=self._run_preview,
                args=(preview_text,),
                name="archeon-tts-preview",
                daemon=False,
            )
            self._thread.start()
            return True

    def _run_preview(self, text: str) -> None:
        try:
            self._events.publish("assistant.speaking.started", {"preview": True}, source="voice")
            self._tts.speak(
                text,
                self._tts_stop_event,
                locale=self._locale_provider(),
                **self._tts_config_provider(),
            )
            self._events.publish("assistant.speaking.ended", {"preview": True}, source="voice")
        except Exception as error:
            self._events.publish("voice.preview.error", {"error": str(error)}, source="voice")
        finally:
            with self._lock:
                self._busy = False
                self._thread = None

    def _capture_utterance(self) -> bytes:
        import webrtcvad

        profile = resolve_profile(self._profile_provider())
        vad = webrtcvad.Vad(profile.vad_mode)
        pre_roll: deque[bytes] = deque(maxlen=10)
        recent: deque[bool] = deque(maxlen=5)
        frames: list[bytes] = []
        speech_started = False
        silence_frames = 0
        total_frames = 0
        last_level = 0

        backend = self._audio.acquire(
            AudioMode.CAPTURING,
            config=AudioSessionConfig(
                sample_rate=self.SAMPLE_RATE,
                channels=1,
                block_ms=self.FRAME_MS,
                input_device_id=(
                    self._input_device_provider()
                    if self._input_device_provider is not None
                    else self._input_device_id
                ),
            ),
        )
        if not isinstance(backend, WasapiSharedCapture):
            raise RuntimeError("invalid capture backend")
        self._events.publish("speech.listening.started", source="voice")

        def consume(chunk: bytes) -> bool:
            nonlocal speech_started, silence_frames, total_frames, last_level
            total_frames += 1
            voiced = vad.is_speech(chunk, self.SAMPLE_RATE)
            recent.append(voiced)
            samples = array("h")
            samples.frombytes(chunk)
            if total_frames - last_level >= 5:
                rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
                self._events.publish(
                    "speech.audio.level",
                    {"level": round(min(1.0, rms / 12_000), 3)},
                    source="voice",
                )
                last_level = total_frames
            if not speech_started:
                pre_roll.append(chunk)
                if len(recent) == recent.maxlen and sum(recent) >= 3:
                    speech_started = True
                    frames.extend(pre_roll)
                return total_frames < 400
            frames.append(chunk)
            silence_frames = silence_frames + 1 if not voiced else 0
            silence_limit = max(1, profile.silence_ms // self.FRAME_MS)
            utterance_limit = max(1, profile.max_utterance_ms // self.FRAME_MS)
            return silence_frames < silence_limit and len(frames) < utterance_limit

        try:
            backend.capture(self._stop_event, consume)
        finally:
            self._audio.release()
            self._events.publish(
                "speech.listening.ended", {"speech_detected": speech_started}, source="voice"
            )
        return b"".join(frames)

    def _capture_barge_utterance(self, result: dict[str, Any]) -> None:
        import webrtcvad

        profile = resolve_profile(self._profile_provider())
        vad = webrtcvad.Vad(profile.vad_mode)
        pre_roll: deque[bytes] = deque(maxlen=10)
        recent: deque[bool] = deque(maxlen=5)
        frames: list[bytes] = []
        speech_started = False
        silence_frames = 0
        total_frames = 0
        last_level = 0
        backend = None
        try:
            backend = self._audio.acquire(
                AudioMode.CAPTURING,
                config=AudioSessionConfig(
                    sample_rate=self.SAMPLE_RATE,
                    channels=1,
                    block_ms=self.FRAME_MS,
                    input_device_id=(
                        self._input_device_provider()
                        if self._input_device_provider is not None
                        else self._input_device_id
                    ),
                ),
            )
            if not isinstance(backend, WasapiSharedCapture):
                raise RuntimeError("invalid capture backend")

            def consume(chunk: bytes) -> bool:
                nonlocal speech_started, silence_frames, total_frames, last_level
                total_frames += 1
                voiced = vad.is_speech(chunk, self.SAMPLE_RATE)
                recent.append(voiced)
                if not speech_started:
                    pre_roll.append(chunk)
                    if total_frames >= 20 and len(recent) == recent.maxlen and sum(recent) >= 4:
                        speech_started = True
                        frames.extend(pre_roll)
                        self._tts_stop_event.set()
                        self._events.publish("voice.barge_in.detected", source="voice")
                        self._events.publish("speech.listening.started", {"barge_in": True}, source="voice")
                    return True
                frames.append(chunk)
                silence_frames = silence_frames + 1 if not voiced else 0
                if total_frames - last_level >= 5:
                    samples = array("h")
                    samples.frombytes(chunk)
                    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
                    self._events.publish(
                        "speech.audio.level",
                        {"level": round(min(1.0, rms / 12_000), 3)},
                        source="voice",
                    )
                    last_level = total_frames
                return (
                    silence_frames < max(1, profile.silence_ms // self.FRAME_MS)
                    and len(frames) < max(1, profile.max_utterance_ms // self.FRAME_MS)
                )

            backend.capture(self._barge_monitor_stop, consume)
            if speech_started:
                result["pcm"] = b"".join(frames)
                self._events.publish("speech.listening.ended", {"speech_detected": True, "barge_in": True}, source="voice")
        except Exception as error:
            result["error"] = str(error)
        finally:
            if backend is not None:
                self._audio.release()

    def _speak_with_optional_barge_in(self, text: str, tts: dict[str, Any]) -> bytes:
        result: dict[str, Any] = {}
        monitor: Thread | None = None
        self._tts_stop_event.clear()
        self._barge_monitor_stop.clear()
        if self._barge_in_provider():
            monitor = Thread(
                target=self._capture_barge_utterance,
                args=(result,),
                name="archeon-barge-in",
                daemon=False,
            )
            monitor.start()
        try:
            self._tts.speak(
                text,
                self._tts_stop_event,
                locale=self._locale_provider(),
                voice_id=tts.get("voice_id"),
                output_device_id=tts.get("output_device_id"),
                rate=tts.get("rate"),
                volume=tts.get("volume"),
            )
        finally:
            if monitor is not None:
                if not self._tts_stop_event.is_set():
                    self._barge_monitor_stop.set()
                monitor.join(timeout=16.0)
                if monitor.is_alive():
                    self._barge_monitor_stop.set()
                    monitor.join(timeout=1.0)
                if monitor.is_alive():
                    raise RuntimeError("barge_in_monitor_did_not_stop")
        return bytes(result.get("pcm", b""))

    def _run_cycle(self) -> None:
        started = time.perf_counter()
        try:
            pcm = self._capture_utterance()
            if self._stop_event.is_set():
                self._events.publish("voice.cycle.cancelled", source="voice")
                return
            if not pcm:
                raise RuntimeError("no_speech_detected")
            for turn in range(3):
                self._events.publish("speech.transcription.started", source="voice")
                text = self._stt.transcribe(pcm, self.SAMPLE_RATE)
                self._events.publish("speech.transcription.completed", {"text": text}, source="voice")
                if not text:
                    raise RuntimeError("empty_transcription")
                self._events.publish("assistant.processing.started", {"text": text}, source="voice")
                response = self._command_handler(text)
                self._events.publish("assistant.processing.completed", response, source="voice")
                if self._stop_event.is_set():
                    self._events.publish("voice.cycle.cancelled", source="voice")
                    return
                spoken = str(response.get("message", ""))
                barge_pcm = b""
                if response.get("ok") and spoken:
                    self._events.publish("assistant.speaking.started", {"text": spoken}, source="voice")
                    barge_pcm = self._speak_with_optional_barge_in(spoken, self._tts_config_provider())
                    self._events.publish("assistant.speaking.ended", source="voice")
                if self._stop_event.is_set():
                    self._events.publish("voice.cycle.cancelled", source="voice")
                    return
                if barge_pcm and turn < 2:
                    pcm = barge_pcm
                    continue
                break
            self._events.publish(
                "voice.cycle.completed",
                {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3)},
                source="voice",
            )
        except Exception as error:
            self._events.publish("voice.cycle.error", {"error": str(error)}, source="voice")
        finally:
            self._stt.unload()
            with self._lock:
                self._busy = False
                self._thread = None

    def _start(self) -> None:
        self._audio.register_backend("wasapi_shared", WasapiSharedCapture)
        self.sync_wake_word()

    def _stop(self) -> None:
        self._wake_stop.set()
        self.interrupt()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=15.0)
            if thread.is_alive():
                raise RuntimeError("voice cycle thread did not stop")
        wake_thread = self._wake_thread
        if wake_thread is not None:
            wake_thread.join(timeout=2.0)
            if wake_thread.is_alive():
                raise RuntimeError("wake monitor did not stop")
