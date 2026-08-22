"""Verify that repeated on-demand Vosk work does not accumulate in the Core."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from archeon.voice.providers import VoskSpeechToText


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=5)
    args = parser.parse_args()
    provider = VoskSpeechToText(ROOT / "models" / "vosk-model-small-es-0.42")
    process = psutil.Process()
    pcm = bytes(16_000 * 2)  # One second, 16 kHz, signed 16-bit mono silence.
    samples: list[dict[str, float]] = []
    for cycle in range(max(1, args.cycles)):
        started = time.perf_counter()
        provider.transcribe(pcm, 16_000)
        memory = process.memory_info()
        samples.append({
            "cycle": cycle + 1,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            "rss_mb": round(memory.rss / 1_048_576, 3),
            "private_mb": round(getattr(memory, "private", memory.vms) / 1_048_576, 3),
        })
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "cycles": samples,
        "rss_growth_mb": round(samples[-1]["rss_mb"] - samples[0]["rss_mb"], 3),
        "private_growth_mb": round(samples[-1]["private_mb"] - samples[0]["private_mb"], 3),
        "model_loaded_after": provider.loaded,
        "child_processes_after": len(process.children(recursive=True)),
    }
    target = ROOT / "benchmarks" / "stt-reclaim.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
