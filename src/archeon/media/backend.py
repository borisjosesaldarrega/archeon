"""Lazy miniaudio playback backend; no decoder or device exists at idle."""

from __future__ import annotations

import urllib.parse
import urllib.request
from array import array
from collections.abc import Callable
from threading import Condition, Event, RLock, Thread, Timer, current_thread
from typing import Any


def is_online_media_path(path: str) -> bool:
    """Treat Windows drive paths as files, never as URL schemes."""
    parsed = urllib.parse.urlparse(path)
    return parsed.scheme.casefold() in {"http", "https"} and not (
        len(path) >= 3 and path[0].isalpha() and path[1] == ":" and path[2] in {"\\", "/"}
    )


class BufferedHttpSource:
    """Small bounded producer/consumer buffer for finite HTTPS audio streams."""

    BLOCK_SIZE = 16 * 1024
    BUFFER_SIZE = 256 * 1024
    ffi_handle = None
    error_in_readcallback = None

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("invalid_online_media_url")
        self.url = url
        self._initial_host = parsed.hostname.casefold()
        self._initial_path = parsed.path
        self.content_type = ""
        self._condition = Condition()
        self._buffer = bytearray()
        self._ready = Event()
        self._stop = False
        self._eof = False
        self._error: Exception | None = None
        self._response: Any = None
        self._thread = Thread(target=self._download, name="archeon-media-http", daemon=False)
        self._thread.start()
        if not self._ready.wait(8):
            self.close()
            raise TimeoutError("online_media_connect_timeout")
        if self._error is not None:
            error = self._error
            self.close()
            raise RuntimeError("online_media_connect_failed") from error

    def _download(self) -> None:
        try:
            request = urllib.request.Request(self.url, headers={"Accept": "audio/*", "User-Agent": "ARCHEON/10"})
            # A short CDN pause must not be mistaken for the end of a track.
            # FFmpeg is preferred for authorized online providers, while this
            # bounded fallback tolerates transient read stalls for longer.
            with urllib.request.urlopen(request, timeout=30) as response:
                self._response = response
                final_url = response.geturl() if hasattr(response, "geturl") else self.url
                final = urllib.parse.urlparse(final_url)
                final_host = (final.hostname or "").casefold()
                trusted = (
                    final.scheme == "https"
                    and (
                        final_host == self._initial_host
                        or (self._initial_host.endswith(".jamendo.com") and final_host.endswith(".jamendo.com"))
                        or (
                            self._initial_host == "api.audius.co"
                            and self._initial_path.startswith("/v1/tracks/")
                            and self._initial_path.endswith("/stream")
                            and bool(final_host)
                            and final_host not in {"localhost", "localhost.localdomain"}
                            and not final_host.endswith(".local")
                        )
                    )
                )
                if not trusted:
                    raise ValueError("online_media_redirect_not_trusted")
                self.content_type = (response.headers.get("Content-Type") or "").partition(";")[0].strip().casefold()
                self._ready.set()
                while True:
                    with self._condition:
                        self._condition.wait_for(lambda: self._stop or len(self._buffer) < self.BUFFER_SIZE)
                        if self._stop:
                            return
                    chunk = response.read(self.BLOCK_SIZE)
                    if not chunk:
                        with self._condition:
                            self._eof = True
                            self._condition.notify_all()
                        return
                    with self._condition:
                        self._buffer.extend(chunk)
                        self._condition.notify_all()
        except Exception as error:
            with self._condition:
                self._error = error
                self._eof = True
                self._ready.set()
                self._condition.notify_all()
        finally:
            self._response = None

    def read(self, num_bytes: int) -> bytes:
        with self._condition:
            self._condition.wait_for(lambda: self._buffer or self._eof or self._stop)
            if self._error is not None and not self._buffer:
                raise self._error
            size = min(max(0, num_bytes), len(self._buffer))
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
            self._condition.notify_all()
            return chunk

    def seek(self, _offset: int, _origin: object) -> bool:
        return False

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        response = self._response
        if response is not None:
            try:
                response.close()
            except OSError:
                pass
        if self._thread.is_alive() and self._thread is not current_thread():
            self._thread.join(timeout=2)


class MiniAudioPlayer:
    SAMPLE_RATE = 44_100
    CHANNELS = 2
    BUFFER_SIZE_MSEC = 80
    # miniaudio signals source exhaustion while WASAPI still owns roughly two
    # buffers. Closing immediately clips the tail and advances the queue early.
    OUTPUT_DRAIN_SECONDS = BUFFER_SIZE_MSEC * 2 / 1000

    def __init__(self, *, output_device_id: str | None = None) -> None:
        self._output_device_id = output_device_id
        self._device: Any = None
        self._stream: Any = None
        self._source: Any = None
        self._network_source: BufferedHttpSource | None = None
        self._end_timer: Timer | None = None
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

    def open(
        self, path: str, *, seek_ms: int = 0, on_end: Callable[[], None],
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        import miniaudio

        self.close()
        seek_frame = max(0, round(seek_ms * self.SAMPLE_RATE / 1000))
        network_source = None
        if is_online_media_path(path):
            network_source = BufferedHttpSource(path)
            formats = {
                "audio/mpeg": miniaudio.FileFormat.MP3,
                "audio/flac": miniaudio.FileFormat.FLAC,
                "audio/ogg": miniaudio.FileFormat.VORBIS,
                "application/ogg": miniaudio.FileFormat.VORBIS,
            }
            source = miniaudio.stream_any(
                network_source,
                source_format=formats.get(network_source.content_type, miniaudio.FileFormat.UNKNOWN),
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=self.CHANNELS,
                sample_rate=self.SAMPLE_RATE,
                seek_frame=seek_frame,
            )
        else:
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
                position_ms = round((self._seek_frame + self._position_frames) * 1000 / self.SAMPLE_RATE)
            if on_progress is not None:
                on_progress(position_ms)

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

        def schedule_end() -> None:
            with self._lock:
                if self._device is None:
                    return
                timer = Timer(self.OUTPUT_DRAIN_SECONDS, on_end)
                timer.name = "archeon-media-drain"
                timer.daemon = True
                self._end_timer = timer
                timer.start()

        stream = miniaudio.stream_with_callbacks(
            source,
            progress_callback=progress,
            frame_process_method=apply_volume,
            end_callback=schedule_end,
        )
        next(stream)
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.CHANNELS,
            sample_rate=self.SAMPLE_RATE,
            buffersize_msec=self.BUFFER_SIZE_MSEC,
            device_id=self._select_device(miniaudio),
            backends=[miniaudio.Backend.WASAPI],
            app_name="ARCHEON",
        )
        with self._lock:
            self.path = path
            self._seek_frame = seek_frame
            self._position_frames = 0
            self._source = source
            self._network_source = network_source
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
            device, source, network_source = self._device, self._source, self._network_source
            end_timer, self._end_timer = self._end_timer, None
            self._device = None
            self._stream = None
            self._source = None
            self._network_source = None
            self.path = None
        if end_timer is not None:
            end_timer.cancel()
        if device is not None:
            device.close()
        if source is not None:
            try:
                source.close()
            except (AttributeError, RuntimeError):
                pass
        if network_source is not None:
            network_source.close()
