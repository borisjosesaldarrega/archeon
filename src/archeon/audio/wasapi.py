"""Lazy PortAudio/WASAPI shared capture backend."""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event
from typing import Any

from .manager import AudioSessionConfig


class WasapiSharedCapture:
    def __init__(self) -> None:
        self._config: AudioSessionConfig | None = None
        self._stream: Any = None
        self.device: dict[str, Any] | None = None

    @staticmethod
    def devices() -> list[dict[str, Any]]:
        import sounddevice as sd

        apis = sd.query_hostapis()
        wasapi = next((index for index, api in enumerate(apis) if api["name"] == "Windows WASAPI"), None)
        if wasapi is None:
            return []
        return [
            dict(device)
            for device in sd.query_devices()
            if device["hostapi"] == wasapi and device["max_input_channels"] > 0
        ]

    def open(self, config: AudioSessionConfig) -> None:
        if config.exclusive or not config.shared:
            raise RuntimeError("exclusive audio is forbidden")
        self._config = config

    def capture(
        self,
        stop: Event,
        consume: Callable[[bytes], bool],
    ) -> None:
        import sounddevice as sd

        assert self._config is not None
        apis = sd.query_hostapis()
        wasapi_index = next(
            (index for index, api in enumerate(apis) if api["name"] == "Windows WASAPI"),
            None,
        )
        if wasapi_index is None:
            raise RuntimeError("WASAPI is unavailable")
        device_id = (
            int(self._config.input_device_id)
            if self._config.input_device_id is not None
            else int(apis[wasapi_index]["default_input_device"])
        )
        device = dict(sd.query_devices(device_id))
        if device["hostapi"] != wasapi_index or device["max_input_channels"] < 1:
            raise RuntimeError("selected device is not a WASAPI input")
        self.device = device
        queue: Queue[bytes] = Queue(maxsize=48)

        def callback(indata, frames, time_info, status) -> None:
            chunk = bytes(indata)
            try:
                queue.put_nowait(chunk)
            except Full:
                try:
                    queue.get_nowait()
                except Empty:
                    pass
                queue.put_nowait(chunk)

        settings = sd.WasapiSettings(exclusive=False, auto_convert=True)
        blocksize = self._config.sample_rate * self._config.block_ms // 1000
        self._stream = sd.RawInputStream(
            samplerate=self._config.sample_rate,
            blocksize=blocksize,
            device=device_id,
            channels=self._config.channels,
            dtype="int16",
            latency="low",
            extra_settings=settings,
            callback=callback,
        )
        self._stream.start()
        try:
            while not stop.is_set():
                try:
                    chunk = queue.get(timeout=0.25)
                except Empty:
                    continue
                if not consume(chunk):
                    break
        finally:
            self.close()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
