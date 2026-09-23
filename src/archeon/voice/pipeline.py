"""One-shot microphone → VAD → STT → assistant → TTS pipeline."""

from __future__ import annotations

import importlib.util
import logging
import math
import time
from array import array
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any
from uuid import uuid4

from archeon.audio import AudioManager, AudioMode, AudioSessionConfig
from archeon.audio.wasapi import WasapiSharedCapture
from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent

from .providers import SapiTextToSpeech, VoskSpeechToText
from .catalog import PROFILES, resolve_model, resolve_profile
from .speaker import SpeakerVerificationManager

logger = logging.getLogger("archeon.voice")


class VoicePipeline(ManagedComponent):
    SAMPLE_RATE = 16_000
    FRAME_MS = 20

    def __init__(
        self,
        events: EventBus,
        audio: AudioManager,
        command_handler: Callable[[str], dict[str, Any]],
        models_root: Path | Callable[[], Path],
        *,
        input_device_id: str | None = None,
        input_device_provider: Callable[[], str | None] | None = None,
        locale_provider: Callable[[], str] | None = None,
        recognition_locale_provider: Callable[[], str] | None = None,
        profile_provider: Callable[[], str] | None = None,
        tts_config_provider: Callable[[], dict[str, Any]] | None = None,
        barge_in_provider: Callable[[], bool] | None = None,
        wake_enabled_provider: Callable[[], bool] | None = None,
        wake_name_provider: Callable[[], str] | None = None,
        speaker_verifier: SpeakerVerificationManager | None = None,
        speaker_verification_enabled_provider: Callable[[], bool] | None = None,
        dictation_repair: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__("voice")
        self._events = events
        self._audio = audio
        self._command_handler = command_handler
        self._models_root_provider = models_root if callable(models_root) else lambda: models_root
        self._profile_provider = profile_provider or (lambda: "eco")
        self._recognition_locale_provider = recognition_locale_provider or (lambda: "es")
        _, model_path = resolve_model(
            self._models_root(), self._profile_provider(), self._recognition_locale_provider()
        )
        self._stt = VoskSpeechToText(model_path)
        self._tts = SapiTextToSpeech()
        self._input_device_id = input_device_id
        self._input_device_provider = input_device_provider
        self._locale_provider = locale_provider or (lambda: "es")
        self._tts_config_provider = tts_config_provider or (lambda: {})
        self._barge_in_provider = barge_in_provider or (lambda: False)
        self._wake_enabled_provider = wake_enabled_provider or (lambda: False)
        self._wake_name_provider = wake_name_provider or (lambda: "Archeon")
        self._speaker_verifier = speaker_verifier
        self._speaker_verification_enabled_provider = speaker_verification_enabled_provider or (lambda: False)
        self._dictation_repair = dictation_repair or (lambda text: text)
        self._stop_event = Event()
        self._tts_stop_event = Event()
        self._barge_monitor_stop = Event()
        self._thread: Thread | None = None
        self._wake_thread: Thread | None = None
        self._wake_stop = Event()
        self._lock = RLock()
        self._busy = False
        self._wake_state = "disabled"
        self._wake_last_error: str | None = None
        self._wake_error_category: str | None = None
        self._wake_error_type: str | None = None
        self._wake_device: dict[str, Any] | None = None
        self._wake_stream_active = False
        self._wake_frames_received = 0
        self._wake_last_frame_at: str | None = None
        self._wake_last_level = 0.0
        self._wake_candidates_total = 0
        self._wake_last_candidate: str | None = None
        self._wake_last_candidate_at: str | None = None
        self._wake_activations_total = 0
        self._wake_last_activation_at: str | None = None
        self._speaker_last_result: dict[str, Any] | None = None
        self._enrollment_thread: Thread | None = None
        self._enrollment_stop = Event()
        self._last_tts_metrics: Any | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def _models_root(self) -> Path:
        return Path(self._models_root_provider()).expanduser().resolve()

    def configure_models_root(self, models_root: Path) -> None:
        with self._lock:
            if self._busy:
                raise RuntimeError("voice_busy")
            self._models_root_provider = lambda: models_root
            self._configure_stt()

    def status(self) -> dict[str, Any]:
        profile = resolve_profile(self._profile_provider())
        model, model_path = resolve_model(
            self._models_root(), profile.name, self._recognition_locale_provider()
        )
        self._stt.configure(model_path)
        dependencies = all(
            importlib.util.find_spec(name) is not None
            for name in ("sounddevice", "webrtcvad", "vosk", "comtypes")
        )
        live_backend = self._audio.backend
        live_device = (
            live_backend.device
            if isinstance(live_backend, WasapiSharedCapture) and live_backend.device
            else self._wake_device
        )
        monitor_active = bool(self._wake_thread and self._wake_thread.is_alive())
        monitor_state = self._wake_state
        if monitor_active and monitor_state == "waiting" and isinstance(live_backend, WasapiSharedCapture) and not live_backend.active:
            monitor_state = "starting"
        return {
            "available": dependencies and self._stt.available,
            "busy": self.busy,
            "stt": self._stt.name,
            "tts": self._tts.name,
            "model_installed": self._stt.available,
            "model_loaded": bool(getattr(self._stt, "loaded", False)),
            "capture": "WASAPI shared",
            "profile": profile.name,
            "model_id": model.id,
            "languages": list(model.languages),
            "wake_word_enabled": self._wake_enabled_provider(),
            "wake_name": self._wake_name_provider(),
            "wake_monitor_active": monitor_active,
            "wake_monitor_state": monitor_state,
            "wake_monitor_error": self._wake_last_error,
            "wake_error_category": self._wake_error_category,
            "wake_error_type": self._wake_error_type,
            "wake_worker_status": monitor_state,
            "wake_backend": "WASAPI shared / WebRTC VAD / Vosk",
            "wake_model_id": model.id,
            "wake_model_path": str(model_path),
            "wake_target_sample_rate": self.SAMPLE_RATE,
            "wake_native_sample_rate": (
                live_device.get("samplerate") or live_device.get("default_samplerate")
                if live_device else None
            ),
            "wake_input_device": dict(live_device) if live_device else None,
            "wake_stream_active": self._wake_stream_active,
            "wake_frames_received": self._wake_frames_received,
            "wake_last_frame_at": self._wake_last_frame_at,
            "wake_input_level": self._wake_last_level,
            "wake_candidates_total": self._wake_candidates_total,
            "wake_last_candidate": self._wake_last_candidate,
            "wake_last_candidate_at": self._wake_last_candidate_at,
            "wake_activations_total": self._wake_activations_total,
            "wake_last_activation_at": self._wake_last_activation_at,
            "speaker_verification_enabled": self._speaker_verification_enabled_provider(),
            "speaker_profiles": self.speaker_profiles(),
            "speaker_last_result": dict(self._speaker_last_result) if self._speaker_last_result else None,
        }

    def speaker_profiles(self) -> list[dict[str, Any]]:
        return self._speaker_verifier.public_profiles() if self._speaker_verifier else []

    def start_speaker_enrollment(self, name: str, *, profile_id: str | None = None, sample_count: int = 3) -> bool:
        if self._speaker_verifier is None or self.busy or (self._enrollment_thread and self._enrollment_thread.is_alive()):
            return False
        self._enrollment_stop.clear()
        self._enrollment_thread = Thread(
            target=self._run_speaker_enrollment,
            args=(name, profile_id, max(3, min(5, int(sample_count)))),
            name="archeon-speaker-enrollment", daemon=False,
        )
        self._enrollment_thread.start()
        return True

    def _run_speaker_enrollment(self, name: str, profile_id: str | None, sample_count: int) -> None:
        correlation_id = uuid4().hex
        samples: list[bytes] = []
        with self._lock:
            self._busy = True
        try:
            if not self._suspend_wake_for_manual_cycle():
                raise RuntimeError("wake_monitor_handoff_timeout")
            for index in range(sample_count):
                self._events.publish("speaker.enrollment.sample.requested", {"index": index + 1, "total": sample_count}, source="voice", correlation_id=correlation_id)
                pcm = self._wake_candidate(self._enrollment_stop)
                if self._enrollment_stop.is_set():
                    raise RuntimeError("speaker_enrollment_cancelled")
                if not pcm:
                    raise ValueError("speaker_sample_empty")
                samples.append(pcm)
                self._events.publish("speaker.enrollment.sample.completed", {"index": index + 1, "total": sample_count}, source="voice", correlation_id=correlation_id)
            profile = self._speaker_verifier.enroll(name, samples, profile_id=profile_id)
            self._events.publish("speaker.enrollment.completed", {"profile": profile}, source="voice", correlation_id=correlation_id)
        except Exception as error:
            logger.exception("Speaker enrollment failed profile_id=%r", profile_id)
            self._events.publish("speaker.enrollment.failed", {"error": str(error)}, source="voice", correlation_id=correlation_id)
        finally:
            with self._lock:
                self._busy = False
            if self._wake_enabled_provider():
                self._wake_stop.clear()
                self.sync_wake_word()

    def update_speaker_profile(self, profile_id: str, *, name: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
        if self._speaker_verifier is None:
            raise RuntimeError("speaker_verification_unavailable")
        return self._speaker_verifier.update(profile_id, name=name, enabled=enabled)

    def delete_speaker_profile(self, profile_id: str) -> None:
        if self._speaker_verifier is None:
            raise RuntimeError("speaker_verification_unavailable")
        self._speaker_verifier.delete(profile_id)

    def _configure_stt(self) -> None:
        self._models_root().mkdir(parents=True, exist_ok=True)
        _, model_path = resolve_model(
            self._models_root(),
            self._profile_provider(),
            self._recognition_locale_provider(),
        )
        self._stt.configure(model_path)

    def sync_wake_word(self) -> None:
        thread = self._wake_thread
        enabled = self._wake_enabled_provider()
        if enabled and thread is not None and thread.is_alive() and self._wake_stop.is_set():
            thread.join(timeout=2.0)
            thread = self._wake_thread
        if enabled and (thread is None or not thread.is_alive()):
            self._wake_stop.clear()
            self._wake_state = "starting"
            self._wake_last_error = None
            self._wake_error_category = None
            self._wake_error_type = None
            self._wake_thread = Thread(target=self._run_wake_monitor, name="archeon-wake-word", daemon=False)
            self._wake_thread.start()
        elif not enabled and thread is not None:
            self._wake_stop.set()
            if thread is not current_thread():
                thread.join(timeout=2.0)
            self._wake_state = "disabled"
        elif not enabled:
            self._wake_state = "disabled"

    def restart_wake_word(self) -> None:
        """Apply a device or wake configuration change without duplicate capture."""
        thread = self._wake_thread
        if thread is not None and thread.is_alive():
            self._wake_stop.set()
            if thread is not current_thread():
                thread.join(timeout=2.0)
        self.sync_wake_word()

    def _suspend_wake_for_manual_cycle(self) -> bool:
        thread = self._wake_thread
        if thread is None or not thread.is_alive() or thread is current_thread():
            return True
        self._wake_state = "suspending"
        self._wake_stop.set()
        thread.join(timeout=2.0)
        if thread.is_alive():
            self._wake_last_error = "wake_monitor_handoff_timeout"
            self._wake_error_category = "audio_handoff_timeout"
            self._wake_error_type = "TimeoutError"
            self._wake_state = "error"
            return False
        return True

    @classmethod
    def split_wake_command(cls, text: str, wake_name: str) -> str | None:
        from difflib import SequenceMatcher
        words = cls._normalize_wake_text(text).split()
        wake_words = cls._normalize_wake_text(wake_name).split()
        if not wake_words or not words:
            return None
        expected = "".join(wake_words)
        product_aliases = {
            "archeon", "arqueon", "archon", "archion", "arquion",
            "archi on", "arche on", "arque on",
        }
        lengths = {len(wake_words)}
        if expected == "archeon":
            # Small Vosk models sometimes split a made-up name into two words.
            lengths.update((1, 2))
        for start in range(min(2, len(words))):
            for length in sorted(lengths):
                if start + length > len(words):
                    continue
                candidate_words = words[start:start + length]
                candidate = " ".join(candidate_words)
                compact = "".join(candidate_words)
                exact = compact == expected
                product_alias = expected == "archeon" and candidate in product_aliases
                fuzzy = (
                    length == len(wake_words)
                    and len(expected) >= 4
                    and abs(len(compact) - len(expected)) <= 1
                    and SequenceMatcher(None, compact, expected).ratio() >= 0.82
                )
                if exact or product_alias or fuzzy:
                    return " ".join(words[start + length:])
        return None

    @staticmethod
    def _normalize_wake_text(text: str) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKD", text.casefold())
        return " ".join("".join(c for c in value if c.isalnum() or c.isspace()).split())

    @staticmethod
    def _classify_wake_error(error: Exception) -> str:
        detail = str(error).casefold()
        if isinstance(error, (ModuleNotFoundError, ImportError)):
            return "backend_missing"
        if isinstance(error, FileNotFoundError) or "model" in detail and ("missing" in detail or "not found" in detail):
            return "model_missing"
        if "failed to create a model" in detail or "vosk_transcription_failed" in detail:
            return "model_load_failed"
        if "audio session already active" in detail or "busy" in detail or "in use" in detail:
            return "audio_device_busy"
        if "sample rate" in detail or "samplerate" in detail:
            return "sample_rate_unsupported"
        if "device" in detail and ("invalid" in detail or "unavailable" in detail or "not found" in detail):
            return "audio_device_unavailable"
        if "permission" in detail or "access denied" in detail:
            return "microphone_permission_denied"
        return "wake_worker_failed"

    def _wake_candidate(self, stop_event: Event | None = None) -> bytes:
        import webrtcvad
        vad = webrtcvad.Vad(3)
        frames: list[bytes] = []
        pre_roll: deque[bytes] = deque(maxlen=12)
        recent: deque[bool] = deque(maxlen=5)
        started = False
        silence = total = 0
        active_stop = stop_event or self._wake_stop
        backend = self._audio.acquire(AudioMode.CAPTURING, config=AudioSessionConfig(
            sample_rate=self.SAMPLE_RATE, channels=1, block_ms=self.FRAME_MS,
            input_device_id=(self._input_device_provider() if self._input_device_provider else self._input_device_id),
        ))
        if not isinstance(backend, WasapiSharedCapture):
            raise RuntimeError("invalid capture backend")
        self._wake_stream_active = True
        if backend.device:
            self._wake_device = {
                "name": str(backend.device.get("name", "")),
                "hostapi": backend.device.get("hostapi"),
                "samplerate": backend.device.get("samplerate") or backend.device.get("default_samplerate"),
            }
        def consume(chunk: bytes) -> bool:
            nonlocal started, silence, total
            total += 1
            self._wake_frames_received += 1
            self._wake_last_frame_at = datetime.now(UTC).isoformat()
            if total % 5 == 0:
                samples = array("h")
                samples.frombytes(chunk)
                rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
                self._wake_last_level = round(min(1.0, rms / 12_000), 3)
                self._events.publish(
                    "wake.audio.level",
                    {"level": self._wake_last_level, "frames": self._wake_frames_received},
                    source="wake",
                )
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
            backend.capture(active_stop, consume)
            if backend.device:
                self._wake_device = {
                    "name": str(backend.device.get("name", "")),
                    "hostapi": backend.device.get("hostapi"),
                    "samplerate": backend.device.get("samplerate") or backend.device.get("default_samplerate"),
                }
        finally:
            self._wake_stream_active = False
            self._audio.release()
        return b"".join(frames)

    def _run_wake_monitor(self) -> None:
        rejected = 0
        consecutive_errors = 0
        correlation_id = uuid4().hex
        self._wake_state = "waiting"
        self._events.publish(
            "wake.monitor.started",
            {"wake_name": self._wake_name_provider()},
            source="wake",
            correlation_id=correlation_id,
        )
        try:
            while not self._wake_stop.is_set() and self._wake_enabled_provider():
                if self.busy:
                    self._wake_stop.wait(0.25)
                    continue
                try:
                    pcm = self._wake_candidate()
                    if not pcm or self._wake_stop.is_set():
                        continue
                    self._wake_state = "checking"
                    self._configure_stt()
                    text = self._stt.transcribe(pcm, self.SAMPLE_RATE)
                    consecutive_errors = 0
                    self._wake_candidates_total += 1
                    self._wake_last_candidate = text.strip()[:80] or "(sin transcripción)"
                    self._wake_last_candidate_at = datetime.now(UTC).isoformat()
                except Exception as error:
                    consecutive_errors += 1
                    self._wake_last_error = str(error)
                    self._wake_error_category = self._classify_wake_error(error)
                    self._wake_error_type = type(error).__name__
                    self._wake_state = "error"
                    logger.exception(
                        "Wake monitor failed category=%s backend=%s model=%s device=%r target_rate=%s",
                        self._wake_error_category,
                        "WASAPI shared / WebRTC VAD / Vosk",
                        resolve_model(self._models_root(), self._profile_provider(), self._recognition_locale_provider())[0].id,
                        self._wake_device,
                        self.SAMPLE_RATE,
                    )
                    self._events.publish(
                        "wake.monitor.error", {
                            "error": str(error),
                            "category": self._wake_error_category,
                            "error_type": self._wake_error_type,
                        }, source="wake",
                        correlation_id=correlation_id,
                    )
                    self._wake_stop.wait(1.0)
                    if consecutive_errors >= 3:
                        logger.error("Wake monitor suspended after %s consecutive failures", consecutive_errors)
                        break
                    continue
                finally:
                    self._stt.unload()
                command = self.split_wake_command(text, self._wake_name_provider())
                if command is None:
                    self._wake_state = "waiting"
                    rejected += 1
                    self._events.publish(
                        "wake.candidate.rejected",
                        {"count": rejected, "candidate": self._wake_last_candidate},
                        source="wake",
                    )
                    continue
                if self._speaker_verification_enabled_provider():
                    if self._speaker_verifier is None:
                        verification = {"authorized": False, "confidence": 0.0, "error": "speaker_verification_unavailable"}
                    else:
                        try:
                            verification = self._speaker_verifier.verify(pcm)
                        except (ValueError, RuntimeError, OSError) as error:
                            verification = {"authorized": False, "confidence": 0.0, "error": str(error)}
                    self._speaker_last_result = dict(verification)
                    if not verification.get("authorized"):
                        self._wake_state = "waiting"
                        self._events.publish("wake.speaker.rejected", verification, source="wake")
                        continue
                    self._events.publish("wake.speaker.authorized", verification, source="wake")
                self._wake_activations_total += 1
                self._wake_last_activation_at = datetime.now(UTC).isoformat()
                self._events.publish("wake.detected", {"wake_name": self._wake_name_provider(), "command": command}, source="wake")
                if command:
                    self._run_wake_command(command)
                else:
                    self.start_cycle()
        finally:
            self._stt.unload()
            if self._wake_enabled_provider() and not self._wake_stop.is_set():
                self._wake_state = "error"
                self._wake_last_error = self._wake_last_error or "wake_monitor_stopped_unexpectedly"
                self._wake_error_category = self._wake_error_category or "wake_worker_stopped"
                self._wake_error_type = self._wake_error_type or "RuntimeError"
            elif self._wake_enabled_provider():
                self._wake_state = "suspended"
            else:
                self._wake_state = "disabled"
            self._events.publish(
                "wake.monitor.stopped", {"state": self._wake_state}, source="wake",
                correlation_id=correlation_id,
            )
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
        if not self._suspend_wake_for_manual_cycle():
            return False
        with self._lock:
            if self._busy:
                self.sync_wake_word()
                return False
            self._busy = True
            self._stop_event.clear()
            self._tts_stop_event.clear()
            self._barge_monitor_stop.clear()
            self._thread = Thread(target=self._run_cycle, name="archeon-voice-cycle", daemon=False)
            self._thread.start()
            return True

    def start_dictation(self) -> bool:
        """Transcribe one utterance into the text bar without executing it."""
        with self._lock:
            if self._busy or not self.status()["available"]:
                return False
        if not self._suspend_wake_for_manual_cycle():
            return False
        with self._lock:
            if self._busy:
                self.sync_wake_word()
                return False
            self._busy = True
            self._stop_event.clear()
            self._thread = Thread(target=self._run_dictation, name="archeon-voice-dictation", daemon=False)
            self._thread.start()
            return True

    def interrupt(self) -> None:
        self._stop_event.set()
        self._tts_stop_event.set()
        self._barge_monitor_stop.set()
        self._enrollment_stop.set()

    def preview(self, text: str, overrides: dict[str, Any] | None = None) -> bool:
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
                args=(preview_text, dict(overrides or {})),
                name="archeon-tts-preview",
                daemon=False,
            )
            self._thread.start()
            return True

    def test_input(self, duration_seconds: float = 3.0) -> bool:
        """Measure the selected microphone briefly without loading STT."""
        duration = max(1.0, min(5.0, float(duration_seconds)))
        with self._lock:
            if self._busy or not self.status()["available"]:
                return False
        if not self._suspend_wake_for_manual_cycle():
            return False
        with self._lock:
            if self._busy:
                self.sync_wake_word()
                return False
            self._busy = True
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run_input_test,
                args=(duration,),
                name="archeon-microphone-test",
                daemon=False,
            )
            self._thread.start()
            return True

    def _run_input_test(self, duration_seconds: float) -> None:
        levels: list[float] = []
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
            self._events.publish("audio.input.test.started", source="voice")
            frame_limit = max(1, int(duration_seconds * 1_000 / self.FRAME_MS))

            def consume(chunk: bytes) -> bool:
                samples = array("h")
                samples.frombytes(chunk)
                rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
                level = round(min(1.0, rms / 12_000), 3)
                levels.append(level)
                self._events.publish("speech.audio.level", {"level": level}, source="voice")
                return len(levels) < frame_limit and not self._stop_event.is_set()

            backend.capture(self._stop_event, consume)
            self._events.publish(
                "audio.input.test.completed",
                {
                    "peak": max(levels, default=0.0),
                    "average": round(sum(levels) / max(1, len(levels)), 3),
                },
                source="voice",
            )
        except Exception as error:
            self._events.publish("audio.input.test.error", {"error": str(error)}, source="voice")
        finally:
            if backend is not None:
                self._audio.release()
            with self._lock:
                self._busy = False
                self._thread = None
            self.sync_wake_word()

    def _run_preview(self, text: str, overrides: dict[str, Any]) -> None:
        try:
            self._events.publish("assistant.speaking.started", {"preview": True}, source="voice")
            configuration = self._tts_config_provider()
            configuration.update(overrides)
            metrics = self._tts.speak(
                text,
                self._tts_stop_event,
                locale=self._locale_provider(),
                **configuration,
            )
            if metrics is not None:
                self._last_tts_metrics = metrics
                self._events.publish("voice.tts.metrics", {
                    "phase": "preview", "provider": metrics.provider,
                    "requested_style": metrics.requested_style, "applied_style": metrics.applied_style,
                    "dispatch_ms": round(metrics.dispatch_ms, 3),
                    "first_audio_ms": round(metrics.first_audio_ms, 3) if metrics.first_audio_ms is not None else None,
                    "total_ms": round(metrics.total_ms, 3),
                }, source="voice")
            self._events.publish("assistant.speaking.ended", {"preview": True}, source="voice")
        except Exception as error:
            self._events.publish("voice.preview.error", {"error": str(error)}, source="voice")
        finally:
            with self._lock:
                self._busy = False
                self._thread = None
            self.sync_wake_word()

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
            metrics = self._tts.speak(
                text,
                self._tts_stop_event,
                locale=self._locale_provider(),
                voice_id=tts.get("voice_id"),
                output_device_id=tts.get("output_device_id"),
                rate=tts.get("rate"),
                volume=tts.get("volume"),
                style=tts.get("style", "natural"),
            )
            if metrics is not None:
                self._last_tts_metrics = metrics
                self._events.publish("voice.tts.metrics", {
                    "phase": "response", "provider": metrics.provider,
                    "requested_style": metrics.requested_style, "applied_style": metrics.applied_style,
                    "dispatch_ms": round(metrics.dispatch_ms, 3),
                    "first_audio_ms": round(metrics.first_audio_ms, 3) if metrics.first_audio_ms is not None else None,
                    "total_ms": round(metrics.total_ms, 3),
                }, source="voice")
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
        cycle_id = uuid4().hex
        stages: dict[str, Any] = {"input_received": 0.0}
        try:
            pcm = self._capture_utterance()
            stages["end_of_speech"] = round((time.perf_counter() - started) * 1000, 3)
            if self._stop_event.is_set():
                self._events.publish("voice.cycle.cancelled", source="voice")
                return
            if not pcm:
                raise RuntimeError("no_speech_detected")
            self._configure_stt()
            for turn in range(3):
                self._events.publish("speech.transcription.started", source="voice")
                text = self._stt.transcribe(pcm, self.SAMPLE_RATE)
                stages["stt_complete"] = round((time.perf_counter() - started) * 1000, 3)
                self._events.publish("speech.transcription.completed", {
                    "text": text, "elapsed_ms": stages["stt_complete"],
                }, source="voice", correlation_id=cycle_id)
                if not text:
                    raise RuntimeError("empty_transcription")
                self._events.publish("assistant.processing.started", {"text": text}, source="voice")
                response = self._command_handler(text)
                stages["routing_complete"] = round((time.perf_counter() - started) * 1000, 3)
                archi_stages = response.get("data", {}).get("metrics", {}).get("end_to_end", {})
                if isinstance(archi_stages, dict):
                    stages["archi"] = dict(archi_stages)
                self._events.publish("assistant.processing.completed", response, source="voice")
                if self._stop_event.is_set():
                    self._events.publish("voice.cycle.cancelled", source="voice")
                    return
                spoken = str(response.get("message", ""))
                barge_pcm = b""
                if response.get("ok") and spoken:
                    stages["first_sentence"] = round((time.perf_counter() - started) * 1000, 3)
                    stages["tts_started"] = stages["first_sentence"]
                    self._events.publish("assistant.speaking.started", {"text": spoken}, source="voice")
                    self._last_tts_metrics = None
                    barge_pcm = self._speak_with_optional_barge_in(spoken, self._tts_config_provider())
                    if self._last_tts_metrics is not None:
                        stages["tts_dispatch_ms"] = round(self._last_tts_metrics.dispatch_ms, 3)
                        if self._last_tts_metrics.first_audio_ms is not None:
                            stages["tts_first_audio"] = round(
                                float(stages["tts_started"]) + self._last_tts_metrics.first_audio_ms, 3,
                            )
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
                {
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "stages": stages,
                },
                source="voice", correlation_id=cycle_id,
            )
        except Exception as error:
            self._events.publish("voice.cycle.error", {"error": str(error)}, source="voice")
        finally:
            self._stt.unload()
            with self._lock:
                self._busy = False
                self._thread = None
            self.sync_wake_word()

    def _run_dictation(self) -> None:
        started = time.perf_counter()
        try:
            pcm = self._capture_utterance()
            if self._stop_event.is_set():
                self._events.publish("speech.dictation.cancelled", source="voice")
                return
            if not pcm:
                raise RuntimeError("no_speech_detected")
            self._configure_stt()
            self._events.publish("speech.transcription.started", {"dictation": True}, source="voice")
            raw_text = self._stt.transcribe(pcm, self.SAMPLE_RATE).strip()
            if not raw_text:
                raise RuntimeError("empty_transcription")
            repaired_text = str(self._dictation_repair(raw_text)).strip() or raw_text
            self._events.publish(
                "speech.dictation.completed",
                {
                    "text": repaired_text,
                    "repaired": repaired_text != raw_text,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                },
                source="voice",
            )
        except Exception as error:
            self._events.publish("speech.dictation.error", {"error": str(error)}, source="voice")
        finally:
            self._stt.unload()
            with self._lock:
                self._busy = False
                self._thread = None
            self.sync_wake_word()

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
        enrollment_thread = self._enrollment_thread
        if enrollment_thread is not None:
            enrollment_thread.join(timeout=15.0)
            if enrollment_thread.is_alive():
                raise RuntimeError("speaker enrollment did not stop")
