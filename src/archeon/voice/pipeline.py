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


class VoicePipeline(ManagedComponent):
    SAMPLE_RATE = 16_000
    FRAME_MS = 20

    def __init__(
        self,
        events: EventBus,
        audio: AudioManager,
        command_handler: Callable[[str], dict[str, Any]],
        model_path: Path,
        *,
        input_device_id: str | None = None,
        input_device_provider: Callable[[], str | None] | None = None,
        locale_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__("voice")
        self._events = events
        self._audio = audio
        self._command_handler = command_handler
        self._stt = VoskSpeechToText(model_path)
        self._tts = SapiTextToSpeech()
        self._input_device_id = input_device_id
        self._input_device_provider = input_device_provider
        self._locale_provider = locale_provider or (lambda: "es")
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def status(self) -> dict[str, Any]:
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
        }

    def devices(self) -> list[dict[str, Any]]:
        return WasapiSharedCapture.devices()

    def start_cycle(self) -> bool:
        with self._lock:
            if self._busy or not self.status()["available"]:
                return False
            self._busy = True
            self._stop_event.clear()
            self._thread = Thread(target=self._run_cycle, name="archeon-voice-cycle", daemon=False)
            self._thread.start()
            return True

    def interrupt(self) -> None:
        self._stop_event.set()

    def _capture_utterance(self) -> bytes:
        import webrtcvad

        vad = webrtcvad.Vad(2)
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
            return silence_frames < 35 and len(frames) < 600

        try:
            backend.capture(self._stop_event, consume)
        finally:
            self._audio.release()
            self._events.publish(
                "speech.listening.ended", {"speech_detected": speech_started}, source="voice"
            )
        return b"".join(frames)

    def _run_cycle(self) -> None:
        started = time.perf_counter()
        try:
            pcm = self._capture_utterance()
            if self._stop_event.is_set():
                self._events.publish("voice.cycle.cancelled", source="voice")
                return
            if not pcm:
                raise RuntimeError("no_speech_detected")
            self._events.publish("speech.transcription.started", source="voice")
            text = self._stt.transcribe(pcm, self.SAMPLE_RATE)
            self._events.publish("speech.transcription.completed", {"text": text}, source="voice")
            if not text:
                raise RuntimeError("empty_transcription")
            self._events.publish("assistant.processing.started", {"text": text}, source="voice")
            response = self._command_handler(text)
            self._events.publish("assistant.processing.completed", response, source="voice")
            if not response.get("ok") or self._stop_event.is_set():
                return
            spoken = str(response.get("message", ""))
            if spoken:
                self._events.publish("assistant.speaking.started", {"text": spoken}, source="voice")
                self._tts.speak(spoken, self._stop_event, locale=self._locale_provider())
                self._events.publish("assistant.speaking.ended", source="voice")
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

    def _stop(self) -> None:
        self.interrupt()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=15.0)
            if thread.is_alive():
                raise RuntimeError("voice cycle thread did not stop")
