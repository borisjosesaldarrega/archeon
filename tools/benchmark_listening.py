"""Measure one real local microphone/STT cycle without retaining the model."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from statistics import mean

import psutil

from archeon.app import ArcheonApplication


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    process = psutil.Process()
    with tempfile.TemporaryDirectory(prefix="archeon-listen-") as temporary:
        app = ArcheonApplication(data_dir=Path(temporary), port=0)
        completed = app.events.subscribe("voice.cycle.*", max_queue=16)
        app.start()
        process.cpu_percent(None)
        started = time.perf_counter()
        accepted = app.handle_action("voice.listen").get("ok", False)
        cpu_samples: list[float] = []
        ram_samples: list[float] = []
        event_type = None
        event_payload = None
        while accepted and time.perf_counter() - started < 20:
            time.sleep(0.1)
            cpu_samples.append(process.cpu_percent(None))
            ram_samples.append(process.memory_info().rss / 1_048_576)
            try:
                event = completed.get(timeout=0)
                if event.type in {"voice.cycle.completed", "voice.cycle.cancelled", "voice.cycle.error"}:
                    event_type = event.type
                    event_payload = dict(event.payload or {})
                    break
            except Empty:
                pass
        app.voice.interrupt()
        time.sleep(0.2)
        lazy_status = {
            "audio_backend_loaded_after": app.audio.backend_loaded,
            "voice_model_loaded_after": app.voice.status().get("model_loaded"),
        }
        app.stop()
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "accepted": accepted,
        "event": event_type,
        "event_payload": event_payload,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cpu_percent_avg": round(mean(cpu_samples), 3) if cpu_samples else None,
        "cpu_percent_peak": round(max(cpu_samples), 3) if cpu_samples else None,
        "ram_mb_avg": round(mean(ram_samples), 3) if ram_samples else None,
        "ram_mb_peak": round(max(ram_samples), 3) if ram_samples else None,
        **lazy_status,
    }
    target = ROOT / "benchmarks" / "listening.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
