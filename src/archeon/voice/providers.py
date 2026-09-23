"""Replaceable local STT and TTS providers."""

from __future__ import annotations

import json
import html
import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from .catalog import VOICE_STYLES, resolve_voice_style


class SpeechToTextProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...
    @property
    def loaded(self) -> bool: ...
    def configure(self, model_path: Path) -> None: ...
    def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...
    def unload(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VoiceProviderCapabilities:
    """Capabilities advertised without loading a voice model."""

    provider: str
    local: bool
    neural: bool
    styles: tuple[str, ...]
    supports_output_selection: bool = False
    exposes_first_audio_timing: bool = False


@dataclass(frozen=True, slots=True)
class SpeechSynthesisMetrics:
    """Timing returned by a provider after one synthesis operation.

    SAPI does not expose a reliable first-buffer callback, so ``first_audio_ms``
    remains ``None`` there. ``dispatch_ms`` is still useful and the API lets a
    future neural provider report true time-to-first-audio without pipeline
    changes.
    """

    provider: str
    requested_style: str
    applied_style: str
    dispatch_ms: float
    total_ms: float
    first_audio_ms: float | None = None


@runtime_checkable
class VoiceProvider(Protocol):
    name: str

    @property
    def capabilities(self) -> VoiceProviderCapabilities: ...

    def speak(
        self,
        text: str,
        stop: Event,
        *,
        locale: str = "es",
        voice_id: str | None = None,
        output_device_id: str | None = None,
        rate: int | None = None,
        volume: int | None = None,
        style: str = "natural",
    ) -> SpeechSynthesisMetrics | None: ...
    def stop(self) -> None: ...


# Compatibility name used by the existing pipeline and external integrations.
TextToSpeechProvider = VoiceProvider


class LocalNeuralVoiceProvider(VoiceProvider, Protocol):
    """Contract for an optional, on-demand local neural TTS implementation.

    This interface deliberately does not select a model or dependency. A future
    implementation must expose lifecycle state so its memory can be reclaimed.
    """

    @property
    def available(self) -> bool: ...
    @property
    def loaded(self) -> bool: ...
    def load(self) -> None: ...
    def unload(self) -> None: ...


def _vosk_transcribe_worker(
    sender: Any,
    model_path: str,
    pcm: bytes,
    sample_rate: int,
) -> None:
    """Load Vosk in a disposable process so all native memory is reclaimed."""
    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model = Model(model_path)
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.AcceptWaveform(pcm)
        sender.send((True, str(json.loads(recognizer.FinalResult()).get("text", "")).strip()))
    except BaseException as error:  # The parent must always receive a bounded failure.
        try:
            sender.send((False, f"{type(error).__name__}: {error}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        sender.close()


class VoskSpeechToText:
    name = "vosk-small-es"

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._worker: Any = None
        self._lock = RLock()

    def configure(self, model_path: Path) -> None:
        with self._lock:
            if model_path != self._model_path:
                self._model_path = model_path

    @property
    def available(self) -> bool:
        return self._model_path.is_dir()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return bool(self._worker and self._worker.is_alive())

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        if not self.available:
            raise RuntimeError("vosk_model_missing")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(
            target=_vosk_transcribe_worker,
            args=(sender, str(self._model_path), pcm, sample_rate),
            name="archeon-vosk-on-demand",
            daemon=True,
        )
        with self._lock:
            self._worker = worker
        started = False
        try:
            worker.start()
            started = True
            sender.close()
            if not receiver.poll(45.0):
                raise RuntimeError("vosk_transcription_timeout")
            ok, value = receiver.recv()
            if not ok:
                raise RuntimeError(f"vosk_transcription_failed: {value}")
            return str(value)
        except (EOFError, OSError) as error:
            raise RuntimeError("vosk_transcription_worker_failed") from error
        finally:
            sender.close()
            receiver.close()
            if started and worker.is_alive():
                worker.terminate()
            if started:
                worker.join(timeout=5.0)
            if started and worker.is_alive():
                worker.kill()
                worker.join(timeout=2.0)
            with self._lock:
                if self._worker is worker:
                    self._worker = None

    def unload(self) -> None:
        with self._lock:
            worker = self._worker
        if worker and worker.is_alive():
            worker.terminate()


class WindowsSapiProvider:
    name = "windows-sapi"

    def __init__(self, *, rate: int = 0, volume: int = 100) -> None:
        self.rate = max(-10, min(10, rate))
        self.volume = max(0, min(100, volume))
        self._voice: Any = None
        self._lock = RLock()
        self._last_metrics: SpeechSynthesisMetrics | None = None

    @property
    def capabilities(self) -> VoiceProviderCapabilities:
        return VoiceProviderCapabilities(
            provider=self.name,
            local=True,
            neural=False,
            styles=tuple(style for style in VOICE_STYLES if style != "custom"),
            supports_output_selection=True,
            exposes_first_audio_timing=False,
        )

    @property
    def last_metrics(self) -> SpeechSynthesisMetrics | None:
        return self._last_metrics

    @staticmethod
    def voices() -> list[dict[str, Any]]:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            result = []
            for item in voice.GetVoices():
                try:
                    from archeon.core.language import LOCALE_SPECS

                    raw = str(item.GetAttribute("Language") or "")
                    langids = tuple(int(value.strip(), 16) for value in raw.split(";") if value.strip())
                    locales = tuple(
                        code for code, spec in LOCALE_SPECS.items()
                        if spec.primary_langid is not None and any((langid & 0x03FF) == spec.primary_langid for langid in langids)
                    )
                    result.append({
                        "id": item.Id, "name": item.GetDescription(),
                        "locales": list(locales), "language_ids": [f"{value:04X}" for value in langids],
                    })
                except Exception:
                    continue
            return result
        except Exception:
            return []
        finally:
            comtypes.CoUninitialize()

    @staticmethod
    def outputs() -> list[dict[str, str]]:
        import ctypes

        class WaveOutCaps(ctypes.Structure):
            _fields_ = (
                ("manufacturer_id", ctypes.c_ushort),
                ("product_id", ctypes.c_ushort),
                ("driver_version", ctypes.c_uint),
                ("name", ctypes.c_wchar * 32),
                ("formats", ctypes.c_uint),
                ("channels", ctypes.c_ushort),
                ("reserved", ctypes.c_ushort),
                ("support", ctypes.c_uint),
            )

        winmm = ctypes.windll.winmm
        result = []
        for device_id in range(int(winmm.waveOutGetNumDevs())):
            capabilities = WaveOutCaps()
            if winmm.waveOutGetDevCapsW(
                device_id, ctypes.byref(capabilities), ctypes.sizeof(capabilities)
            ) == 0:
                result.append({"id": f"winmm:{device_id}", "name": capabilities.name})
        return result

    def speak(
        self,
        text: str,
        stop: Event,
        *,
        locale: str = "es",
        voice_id: str | None = None,
        output_device_id: str | None = None,
        rate: int | None = None,
        volume: int | None = None,
        style: str = "natural",
    ) -> SpeechSynthesisMetrics:
        import comtypes
        import comtypes.client

        operation_started = perf_counter()
        dispatch_ms = 0.0
        requested_style = style
        applied_style = resolve_voice_style(style, self.capabilities.styles)
        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            selected_rate = self.rate if rate is None else max(-10, min(10, int(rate)))
            voice.Rate = max(-10, min(10, selected_rate + applied_style.rate_delta))
            voice.Volume = self.volume if volume is None else max(0, min(100, int(volume)))
            from archeon.core.language import LOCALE_SPECS, normalize_locale

            locale_code = normalize_locale(locale)
            expected_primary_langid = LOCALE_SPECS[locale_code].primary_langid

            def matches_locale(candidate) -> bool:
                try:
                    raw = str(candidate.GetAttribute("Language") or "")
                    langids = [int(item.strip(), 16) for item in raw.split(";") if item.strip()]
                    return any((langid & 0x03FF) == expected_primary_langid for langid in langids)
                except (AttributeError, TypeError, ValueError):
                    description = str(candidate.GetDescription()).casefold()
                    spec = LOCALE_SPECS[locale_code]
                    return spec.native_name.casefold() in description or spec.english_name.casefold() in description
            matching_voice = next(
                (
                    candidate
                    for candidate in voice.GetVoices()
                    if candidate.Id == voice_id
                ),
                None,
            ) if voice_id else next((candidate for candidate in voice.GetVoices() if matches_locale(candidate)), None)
            if matching_voice is not None:
                voice.Voice = matching_voice
            if output_device_id:
                if not output_device_id.startswith("winmm:"):
                    raise RuntimeError("selected_tts_output_unavailable")
                try:
                    selected_device = int(output_device_id.partition(":")[2])
                except ValueError as error:
                    raise RuntimeError("selected_tts_output_unavailable") from error
                valid_devices = {int(item["id"].partition(":")[2]) for item in self.outputs()}
                if selected_device not in valid_devices:
                    raise RuntimeError("selected_tts_output_unavailable")
                audio_output = comtypes.client.CreateObject("SAPI.SpMMAudioOut")
                audio_output.DeviceId = selected_device
                voice.AudioOutputStream = audio_output
            with self._lock:
                self._voice = voice
            pitch = applied_style.pitch
            spoken_text = f'<pitch middle="{pitch}">{html.escape(text)}</pitch>' if pitch else text
            voice.Speak(spoken_text, 9 if pitch else 1)
            dispatch_ms = (perf_counter() - operation_started) * 1000.0
            while not voice.WaitUntilDone(50):
                if stop.is_set():
                    voice.Speak("", 3)
                    break
        finally:
            with self._lock:
                self._voice = None
            comtypes.CoUninitialize()
        metrics = SpeechSynthesisMetrics(
            provider=self.name,
            requested_style=requested_style,
            applied_style=applied_style.id,
            dispatch_ms=dispatch_ms,
            total_ms=(perf_counter() - operation_started) * 1000.0,
            first_audio_ms=None,
        )
        self._last_metrics = metrics
        return metrics

    def stop(self) -> None:
        with self._lock:
            if self._voice is not None:
                self._voice.Speak("", 3)


# Preserve the old construction API while making the provider role explicit.
SapiTextToSpeech = WindowsSapiProvider
