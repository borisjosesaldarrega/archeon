"""Lazy decoder routing; providers locate media, codecs only decode it."""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse
from array import array
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock, Timer
from typing import Any, Callable

from .backend import MiniAudioPlayer, is_online_media_path


class CodecBackend(StrEnum):
    MINIAUDIO = "miniaudio"
    MEDIA_FOUNDATION = "media_foundation"
    FFMPEG_OPTIONAL = "ffmpeg_optional"
    OFFICIAL_WEB = "official_web"


@dataclass(frozen=True, slots=True)
class CodecDecision:
    backend: CodecBackend
    reason: str
    available: bool
    fallback: CodecBackend | None = None

    def public(self) -> dict[str, object]:
        return asdict(self)


class FFmpegProvider:
    """Optional isolated decoder process; never resolves or downloads content."""

    AUTHORIZED_REMOTE_PROVIDERS = frozenset({"jamendo", "audius", "authorized", "legacy_local"})

    def __init__(self, runtime_root: Path, *, executable: Path | None = None) -> None:
        managed = runtime_root / "media-codecs" / "ffmpeg" / "ffmpeg.exe"
        discovered = shutil.which("ffmpeg")
        self.executable = executable or (managed if managed.is_file() else (Path(discovered) if discovered else None))

    @property
    def available(self) -> bool:
        return bool(self.executable and self.executable.is_file())

    def create_player(self, *, output_device_id: str | None, provider: str) -> "FFmpegPCMPlayer":
        if not self.available or self.executable is None:
            raise RuntimeError("optional_codec_runtime_unavailable")
        return FFmpegPCMPlayer(
            self.executable,
            output_device_id=output_device_id,
            remote_authorized=provider in self.AUTHORIZED_REMOTE_PROVIDERS,
        )


class CodecRouter:
    """Select the lightest decoder without conflating provider and decoder."""

    MINIAUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".ogg"})
    MEDIA_FOUNDATION_SUFFIXES = frozenset({".aac", ".m4a", ".wma", ".asf", ".mp4"})

    def __init__(
        self,
        runtime_root: Path,
        *,
        ffmpeg: FFmpegProvider | None = None,
        media_foundation_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg or FFmpegProvider(runtime_root)
        self._media_foundation_factory = media_foundation_factory

    def select(self, source: str, *, provider: str = "local") -> CodecDecision:
        if provider in {"youtube", "youtube_visual"}:
            return CodecDecision(CodecBackend.OFFICIAL_WEB, "official_player_required", True)
        if provider == "legacy_local":
            return CodecDecision(
                CodecBackend.FFMPEG_OPTIONAL, "legacy_local_stream_requires_isolated_decoder",
                self.ffmpeg.available,
            )
        suffix = Path(urllib.parse.urlparse(source).path).suffix.casefold()
        if is_online_media_path(source):
            if provider in FFmpegProvider.AUTHORIZED_REMOTE_PROVIDERS and self.ffmpeg.available:
                return CodecDecision(
                    CodecBackend.FFMPEG_OPTIONAL,
                    "authorized_remote_stream_with_reconnect",
                    True,
                    CodecBackend.MINIAUDIO,
                )
            return CodecDecision(CodecBackend.MINIAUDIO, "authorized_https_stream", True)
        if suffix in self.MINIAUDIO_SUFFIXES or not suffix:
            return CodecDecision(CodecBackend.MINIAUDIO, "common_local_format", True)
        if suffix in self.MEDIA_FOUNDATION_SUFFIXES:
            return CodecDecision(
                CodecBackend.MEDIA_FOUNDATION, "windows_native_format_adapter_pending",
                os.name == "nt" and self._media_foundation_factory is not None,
                CodecBackend.FFMPEG_OPTIONAL if self.ffmpeg.available else None,
            )
        return CodecDecision(CodecBackend.FFMPEG_OPTIONAL, "optional_codec_required", self.ffmpeg.available)

    def create_player(self, source: str, *, provider: str, output_device_id: str | None) -> Any:
        decision = self.select(source, provider=provider)
        if decision.backend is CodecBackend.OFFICIAL_WEB:
            raise RuntimeError("official_web_player_required")
        if decision.backend is CodecBackend.MINIAUDIO:
            player = MiniAudioPlayer(output_device_id=output_device_id)
            player.codec_backend = CodecBackend.MINIAUDIO.value
            return player
        if decision.backend is CodecBackend.MEDIA_FOUNDATION and self._media_foundation_factory is not None:
            return self._media_foundation_factory(output_device_id=output_device_id)
        # Media Foundation is preferred for native Windows formats. Until its
        # SourceReader adapter lands, the optional worker is the isolated fallback.
        if decision.backend is CodecBackend.MEDIA_FOUNDATION and not self.ffmpeg.available:
            raise RuntimeError("media_foundation_adapter_unavailable")
        return self.ffmpeg.create_player(output_device_id=output_device_id, provider=provider)


class FFmpegPCMPlayer:
    """Decode one permitted source to bounded PCM stdout and play through WASAPI."""

    SAMPLE_RATE = MiniAudioPlayer.SAMPLE_RATE
    CHANNELS = MiniAudioPlayer.CHANNELS
    BUFFER_SIZE_MSEC = MiniAudioPlayer.BUFFER_SIZE_MSEC
    OUTPUT_DRAIN_SECONDS = MiniAudioPlayer.OUTPUT_DRAIN_SECONDS
    codec_backend = CodecBackend.FFMPEG_OPTIONAL.value

    def __init__(self, executable: Path, *, output_device_id: str | None, remote_authorized: bool) -> None:
        self._executable = executable
        self._output_device_id = output_device_id
        self._remote_authorized = remote_authorized
        self._device: Any = None
        self._stream: Any = None
        self._process: subprocess.Popen[bytes] | None = None
        self._end_timer: Timer | None = None
        self._lock = RLock()
        self._volume = 0.7
        self._position_frames = 0
        self._seek_frame = 0
        self.path: str | None = None

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

    def open(self, path: str, *, seek_ms: int = 0, on_end, on_progress=None) -> None:
        import miniaudio

        self.close()
        online = is_online_media_path(path)
        if online and not self._remote_authorized:
            raise RuntimeError("remote_media_not_authorized_for_optional_decoder")
        if not online:
            resolved = Path(path).expanduser().resolve(strict=True)
            if not resolved.is_file():
                raise ValueError("media_path_is_not_a_file")
            path = str(resolved)
        command = [str(self._executable), "-nostdin", "-hide_banner", "-loglevel", "error"]
        if seek_ms > 0:
            command.extend(("-ss", f"{seek_ms / 1000:.3f}"))
        if online:
            command.extend((
                "-reconnect", "1", "-reconnect_streamed", "1",
                "-reconnect_at_eof", "0", "-reconnect_delay_max", "5",
                "-rw_timeout", "15000000",
            ))
        command.extend(("-i", path, "-map", "0:a:0", "-vn", "-sn", "-dn", "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(self.SAMPLE_RATE), "-ac", str(self.CHANNELS), "pipe:1"))
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.CHANNELS,
            sample_rate=self.SAMPLE_RATE,
            buffersize_msec=self.BUFFER_SIZE_MSEC,
            device_id=self._select_device(miniaudio),
            backends=[miniaudio.Backend.WASAPI],
            app_name="ARCHEON",
        )
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                bufsize=self.SAMPLE_RATE * self.CHANNELS,
            )
        except Exception:
            device.close()
            raise
        assert process.stdout is not None

        def pcm_frames():
            required = yield array("h")
            while True:
                body = process.stdout.read(max(1, int(required)) * self.CHANNELS * 2)
                if not body:
                    return
                samples = array("h");samples.frombytes(body[: len(body) - (len(body) % 2)])
                required = yield samples

        source = pcm_frames()
        next(source)

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
            samples = frame if isinstance(frame, array) else array("h", frame)
            return array("h", (max(-32768, min(32767, int(sample * volume))) for sample in samples))

        def schedule_end() -> None:
            with self._lock:
                if self._device is None:
                    return
                timer = Timer(self.OUTPUT_DRAIN_SECONDS, on_end)
                timer.name = "archeon-ffmpeg-drain"
                timer.daemon = True
                self._end_timer = timer
                timer.start()

        try:
            stream = miniaudio.stream_with_callbacks(
                source,
                progress_callback=progress,
                frame_process_method=apply_volume,
                end_callback=schedule_end,
            )
            next(stream)
        except Exception:
            device.close()
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            raise
        with self._lock:
            self.path = path
            self._seek_frame = round(seek_ms * self.SAMPLE_RATE / 1000)
            self._position_frames = 0
            self._process = process
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
            device, stream, process = self._device, self._stream, self._process
            timer, self._end_timer = self._end_timer, None
            self._device = None;self._stream = None;self._process = None;self.path = None
        if timer is not None:
            timer.cancel()
        if device is not None:
            device.close()
        if stream is not None:
            try:
                stream.close()
            except (AttributeError, RuntimeError):
                pass
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
