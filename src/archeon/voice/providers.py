"""Replaceable local STT and TTS providers."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from threading import Event, RLock
from typing import Any, Protocol


class SpeechToTextProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...
    @property
    def loaded(self) -> bool: ...
    def configure(self, model_path: Path) -> None: ...
    def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...
    def unload(self) -> None: ...


class TextToSpeechProvider(Protocol):
    name: str

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
    ) -> None: ...
    def stop(self) -> None: ...


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


class SapiTextToSpeech:
    name = "windows-sapi"

    def __init__(self, *, rate: int = 0, volume: int = 100) -> None:
        self.rate = max(-10, min(10, rate))
        self.volume = max(0, min(100, volume))
        self._voice: Any = None
        self._lock = RLock()

    @staticmethod
    def voices() -> list[dict[str, str]]:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            return [
                {"id": item.Id, "name": item.GetDescription()}
                for item in voice.GetVoices()
            ]
        finally:
            comtypes.CoUninitialize()

    @staticmethod
    def outputs() -> list[dict[str, str]]:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            return [
                {"id": item.Id, "name": item.GetDescription()}
                for item in voice.GetAudioOutputs()
            ]
        finally:
            comtypes.CoUninitialize()

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
    ) -> None:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            voice.Rate = self.rate if rate is None else max(-10, min(10, int(rate)))
            voice.Volume = self.volume if volume is None else max(0, min(100, int(volume)))
            language = "Spanish" if locale.lower().startswith("es") else "English"
            matching_voice = next(
                (
                    candidate
                    for candidate in voice.GetVoices()
                    if candidate.Id == voice_id
                ),
                None,
            ) if voice_id else next(
                (candidate for candidate in voice.GetVoices() if language.casefold() in candidate.GetDescription().casefold()),
                None,
            )
            if matching_voice is not None:
                voice.Voice = matching_voice
            if output_device_id:
                matching_output = next(
                    (candidate for candidate in voice.GetAudioOutputs() if candidate.Id == output_device_id),
                    None,
                )
                if matching_output is None:
                    raise RuntimeError("selected_tts_output_unavailable")
                voice.AudioOutput = matching_output
            with self._lock:
                self._voice = voice
            voice.Speak(text, 1)
            while not voice.WaitUntilDone(50):
                if stop.is_set():
                    voice.Speak("", 3)
                    break
        finally:
            with self._lock:
                self._voice = None
            comtypes.CoUninitialize()

    def stop(self) -> None:
        with self._lock:
            if self._voice is not None:
                self._voice.Speak("", 3)
