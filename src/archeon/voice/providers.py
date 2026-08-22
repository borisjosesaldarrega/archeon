"""Replaceable local STT and TTS providers."""

from __future__ import annotations

import json
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


class VoskSpeechToText:
    name = "vosk-small-es"

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model: Any = None
        self._lock = RLock()

    def configure(self, model_path: Path) -> None:
        with self._lock:
            if model_path != self._model_path:
                self._model = None
                self._model_path = model_path

    @property
    def available(self) -> bool:
        return self._model_path.is_dir()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        if not self.available:
            raise RuntimeError("vosk_model_missing")
        with self._lock:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            if self._model is None:
                self._model = Model(str(self._model_path))
            recognizer = KaldiRecognizer(self._model, sample_rate)
            recognizer.AcceptWaveform(pcm)
            return str(json.loads(recognizer.FinalResult()).get("text", "")).strip()

    def unload(self) -> None:
        with self._lock:
            self._model = None


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
