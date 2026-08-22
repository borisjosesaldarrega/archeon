"""Measure cold and warm local command latency without a desktop renderer."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from archeon.app import ArcheonApplication


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        application = ArcheonApplication(data_dir=Path(temporary))
        application.start()
        started = time.perf_counter()
        first = application.handle_command("estado del sistema")
        cold_ms = (time.perf_counter() - started) * 1000
        warm: list[float] = []
        for _ in range(100):
            started = time.perf_counter()
            response = application.handle_command("estado del sistema")
            warm.append((time.perf_counter() - started) * 1000)
            if not response["ok"]:
                raise RuntimeError(response)
        application.stop()
    ordered = sorted(warm)
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "command": "estado del sistema",
        "cold_lazy_load_ms": round(cold_ms, 3),
        "warm_mean_ms": round(mean(warm), 3),
        "warm_median_ms": round(median(warm), 3),
        "warm_p95_ms": round(ordered[94], 3),
        "iterations": len(warm),
        "success": bool(first["ok"]),
    }
    target = ROOT / "benchmarks" / "command_latency.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
