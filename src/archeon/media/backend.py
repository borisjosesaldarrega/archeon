"""Lazy miniaudio playback backend; no decoder or device exists at idle."""

from __future__ import annotations

from array import array
from collections.abc import Callable
from threading import RLock
from typing import Any


class MiniAudioPlayer:
    SAMPLE_RATE = 44_100
    CHANNELS = 2

    def __init__(self, *, output_device_id: str | None = None) -> None:
        self._output_device_id = output_device_id
        self._device: Any = None
        self._stream: Any = None
        self._source: Any = None
        self._lock = RLock()
        self._volume = 0.7
        self._position_frames = 0
        self._seek_frame = 0
        self.path: str | None = None

    @staticmethod
    def devices() -> list[dict[str, Any]]:
        import miniaudio

        devices = miniaudio.Devices(backends=[miniaudio.Backend.WASAPI]).get_playbacks()
        return [{"id": str(index), "name": item["name"]} for index, item in enumerate(devices)]

    @property
    def position_ms(self) -> int:
        with self._lock:
            return round((self._seek_frame + self._position_frames) * 1000 / self.SAMPLE_RATE)

    def _select_device(self, miniaudio) -> Any:
        if self._output_device_id is None:
            return None
        devices = miniaudio.Devices(backends=[miniaudio.Backend.WASAPI]).get_playbacks()
        try:
            return devices[int(self._output_device_id)]["id"]
        except (ValueError, IndexError, KeyError):
            raise RuntimeError("selected_output_device_unavailable") from None

    def open(self, path: str, *, seek_ms: int = 0, on_end: Callable[[], None]) -> None:
        import miniaudio

        self.close()
        seek_frame = max(0, round(seek_ms * self.SAMPLE_RATE / 1000))
        source = miniaudio.stream_file(
            path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.CHANNELS,
            sample_rate=self.SAMPLE_RATE,
            seek_frame=seek_frame,
        )

        def progress(frames: int) -> None:
            with self._lock:
                self._position_frames += frames

        def apply_volume(frame):
            with self._lock:
                volume = self._volume
            if volume >= 0.999:
                return frame
            if volume <= 0.001:
                return bytes(len(frame) * frame.itemsize) if isinstance(frame, array) else bytes(len(frame))
            samples = frame
            if not isinstance(samples, array):
                samples = array("h")
                samples.frombytes(bytes(frame))
            return array("h", (max(-32768, min(32767, int(sample * volume))) for sample in samples))

        stream = miniaudio.stream_with_callbacks(
            source,
            progress_callback=progress,
            frame_process_method=apply_volume,
            end_callback=on_end,
        )
        next(stream)
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.CHANNELS,
            sample_rate=self.SAMPLE_RATE,
            buffersize_msec=80,
            device_id=self._select_device(miniaudio),
            backends=[miniaudio.Backend.WASAPI],
            app_name="ARCHEON",
        )
        with self._lock:
            self.path = path
            self._seek_frame = seek_frame
            self._position_frames = 0
            self._source = source
            self._stream = stream
            self._device = device

    def play(self) -> None:
        with self._lock:
            if self._device is None or self._stream is None:
                raise RuntimeError("media_not_loaded")
            if not self._device.running:
                self._device.start(self._stream)

    def pause(self) -> None:
        with self._lock:
            if self._device is not None and self._device.running:
                self._device.stop()

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))

    def close(self) -> None:
        with self._lock:
            device, source = self._device, self._source
            self._device = None
            self._stream = None
            self._source = None
            self.path = None
        if device is not None:
            device.close()
        if source is not None:
            try:
                source.close()
            except (AttributeError, RuntimeError):
                pass
