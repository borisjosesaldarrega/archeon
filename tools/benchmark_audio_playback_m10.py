"""Measure ARCHEON's real miniaudio/WASAPI playback clock at common rates."""

from __future__ import annotations

import json
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path
from threading import Event

from archeon.media.backend import MiniAudioPlayer


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "M10_AUDIO_PLAYBACK_TIMING.json"
EXPECTED_SECONDS = 1.0
SAMPLE_RATES = (32_000, 44_100, 48_000)
MAX_CLOCK_ERROR_PERCENT = 12.0


def silent_wave(path: Path, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(MiniAudioPlayer.CHANNELS)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(bytes(sample_rate * MiniAudioPlayer.CHANNELS * 2))


def measure(sample_rate: int, directory: Path) -> dict[str, object]:
    path = directory / f"silent-{sample_rate}.wav"
    silent_wave(path, sample_rate)
    ended = Event()
    player = MiniAudioPlayer()
    started = time.perf_counter()
    try:
        player.open(str(path), on_end=ended.set)
        player.play()
        completed = ended.wait(4.0)
        elapsed = time.perf_counter() - started
        position_ms = player.position_ms
    finally:
        player.close()
    error_percent = abs(elapsed - EXPECTED_SECONDS) / EXPECTED_SECONDS * 100
    return {
        "input_sample_rate": sample_rate,
        "output_sample_rate": MiniAudioPlayer.SAMPLE_RATE,
        "expected_seconds": EXPECTED_SECONDS,
        "wall_seconds": round(elapsed, 6),
        "reported_position_ms": position_ms,
        "clock_error_percent": round(error_percent, 3),
        "ended_callback": completed,
        "passed": completed and error_percent <= MAX_CLOCK_ERROR_PERCENT,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="archeon-m10-audio-") as temp:
        rows = [measure(rate, Path(temp)) for rate in SAMPLE_RATES]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "backend": "miniaudio + Windows WASAPI",
        "fixture": "one-second silent stereo PCM WAV",
        "purpose": "detect sample-rate reinterpretation and fast/slow playback",
        "threshold_clock_error_percent": MAX_CLOCK_ERROR_PERCENT,
        "passed": all(bool(row["passed"]) for row in rows),
        "cases": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
