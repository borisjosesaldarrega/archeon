"""Replaceable local STT and TTS providers."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, RLock
from typing import Any


class VoskSpeechToText:
    name = "vosk-small-es"

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model: Any = None
        self._lock = RLock()

    @property
    def available(self) -> bool:
        return self._model_path.is_dir()

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

    def speak(self, text: str, stop: Event, *, locale: str = "es") -> None:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            voice.Rate = self.rate
            voice.Volume = self.volume
            language = "Spanish" if locale.lower().startswith("es") else "English"
            matching_voice = next(
                (
                    candidate
                    for candidate in voice.GetVoices()
                    if language.casefold() in candidate.GetDescription().casefold()
                ),
                None,
            )
            if matching_voice is not None:
                voice.Voice = matching_voice
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
