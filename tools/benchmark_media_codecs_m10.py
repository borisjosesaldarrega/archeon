"""Measure M10 decoder routing and the optional FFmpeg worker lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Event

import psutil

from archeon.media.codecs import CodecRouter, FFmpegProvider


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "M10_MEDIA_CODEC_BENCHMARK.json"


def main() -> int:
    executable_text = shutil.which("ffmpeg")
    if not executable_text:
        payload = {"status": "optional_runtime_unavailable", "user_verified": False}
        REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload))
        return 0
    executable = Path(executable_text).resolve()
    with tempfile.TemporaryDirectory(prefix="archeon-codec-") as temporary:
        temp = Path(temporary)
        source = temp / "control-48k.webm"
        generated = subprocess.run(
            [
                str(executable), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1.0",
                "-c:a", "libopus", str(source),
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15, check=False,
        )
        if generated.returncode:
            raise RuntimeError(generated.stderr.decode("utf-8", errors="replace"))

        optional = FFmpegProvider(temp, executable=executable)
        router = CodecRouter(temp, ffmpeg=optional)
        decisions = {
            name: router.select(value, provider=provider).public()
            for name, value, provider in (
                ("wav", "control.wav", "local"),
                ("mp3", "control.mp3", "local"),
                ("m4a", "control.m4a", "local"),
                ("webm_opus", str(source), "local"),
                ("youtube", "https://youtube.com/watch?v=test", "youtube_visual"),
            )
        }

        ended = Event()
        player = optional.create_player(output_device_id=None, provider="local")
        player.set_volume(0.0)
        started = time.perf_counter()
        player.open(str(source), on_end=ended.set)
        opened_ms = (time.perf_counter() - started) * 1000
        process = player._process
        if process is None:
            raise RuntimeError("ffmpeg_worker_not_started")
        pid = process.pid
        worker = psutil.Process(pid)
        rss_after_spawn = worker.memory_info().rss
        peak_rss = rss_after_spawn
        cpu_before = sum(worker.cpu_times()[:2])
        cpu_after = cpu_before
        player.play()
        deadline = time.monotonic() + 5.0
        while not ended.wait(0.02) and time.monotonic() < deadline:
            try:
                peak_rss = max(peak_rss, worker.memory_info().rss)
                cpu_after = max(cpu_after, sum(worker.cpu_times()[:2]))
            except psutil.NoSuchProcess:
                pass
        completed = ended.is_set()
        playback_ms = (time.perf_counter() - started) * 1000
        try:
            cpu_after = max(cpu_after, sum(worker.cpu_times()[:2]))
        except psutil.NoSuchProcess:
            cpu_after = cpu_before
        player.close()
        time.sleep(0.1)
        residual = psutil.pid_exists(pid)

        payload = {
            "status": "working_development_runtime",
            "user_verified": False,
            "runtime": {
                "path": str(executable),
                "bytes": executable.stat().st_size,
                "packaged": False,
                "redistribution_approved": False,
                "note": "System GPL full build used only as a development reference; not an ARCHEON package candidate.",
            },
            "routing": decisions,
            "ffmpeg_worker": {
                "fixture": "WebM/Opus, 48 kHz stereo, 1 second silence",
                "spawn_and_open_ms": round(opened_ms, 3),
                "completion_observed": completed,
                "wall_to_drain_ms": round(playback_ms, 3),
                "rss_after_spawn_bytes": rss_after_spawn,
                "peak_rss_bytes": peak_rss,
                "cpu_seconds": round(max(0.0, cpu_after - cpu_before), 4),
                "pid": pid,
                "residual_after_close": residual,
            },
            "idle": {"worker_started_before_request": False, "expected_media_processes": 0},
        }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if residual or not completed else 0


if __name__ == "__main__":
    raise SystemExit(main())
