"""Real microphone soak benchmark for the local wake-word monitor."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from queue import Empty
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import psutil

from archeon.app import ArcheonApplication


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=4.0)
    parser.add_argument("--sample-seconds", type=float, default=2.0)
    parser.add_argument("--wake-name", default="Archeon")
    args = parser.parse_args()
    duration = max(10.0, args.duration_hours * 3600)
    samples: list[tuple[float, float, float]] = []
    counters = {"detections": 0, "rejected_candidates": 0, "errors": 0}
    with tempfile.TemporaryDirectory(prefix="archeon-wake-soak-") as temporary:
        app = ArcheonApplication(data_dir=Path(temporary), port=0)
        subscriptions = {
            "detections": app.events.subscribe("wake.detected", max_queue=512),
            "rejected_candidates": app.events.subscribe("wake.candidate.rejected", max_queue=512),
            "errors": app.events.subscribe("wake.monitor.error", max_queue=512),
        }
        app.start()
        app.configuration.update_settings({"assistant": {"wake_name": args.wake_name, "wake_word_enabled": True, "activation_mode": "wake_word"}})
        app.voice.sync_wake_word()
        process = psutil.Process()
        started = time.monotonic()
        try:
            while time.monotonic() - started < duration:
                cpu = process.cpu_percent(interval=max(0.1, args.sample_seconds))
                memory = process.memory_info()
                rss = memory.rss / 1_048_576
                private = getattr(memory, "private", memory.vms) / 1_048_576
                samples.append((cpu, rss, private))
                for name, subscription in subscriptions.items():
                    while True:
                        try:
                            subscription.get(timeout=0)
                            counters[name] += 1
                        except Empty:
                            break
        except KeyboardInterrupt:
            pass
        finally:
            app.stop()
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "elapsed_hours": round((time.monotonic() - started) / 3600, 4),
        "wake_name": args.wake_name,
        "cpu_percent_avg": round(mean(v[0] for v in samples), 3) if samples else None,
        "cpu_percent_peak": round(max(v[0] for v in samples), 3) if samples else None,
        "ram_mb_avg": round(mean(v[1] for v in samples), 3) if samples else None,
        "ram_mb_peak": round(max(v[1] for v in samples), 3) if samples else None,
        "ram_mb_growth": round(samples[-1][1] - samples[0][1], 3) if samples else None,
        "private_mb_avg": round(mean(v[2] for v in samples), 3) if samples else None,
        "private_mb_peak": round(max(v[2] for v in samples), 3) if samples else None,
        "private_mb_growth": round(samples[-1][2] - samples[0][2], 3) if samples else None,
        **counters,
        "manual_note": "Label spoken trials separately to calculate false negatives; ambient detections are false-positive candidates.",
    }
    target = ROOT / "benchmarks" / "wake-word-soak.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
