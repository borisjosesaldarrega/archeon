"""Measure the disposable native frontend feasibility probe."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import psutil


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    child = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "probe_native_ui.py"), "--auto-exit", "8"],
        cwd=ROOT,
    )
    time.sleep(2.0)
    candidates = [
        process for process in psutil.process_iter(("pid", "name", "cmdline"))
        if "probe_native_ui.py" in " ".join(process.info.get("cmdline") or [])
    ]
    if not candidates:
        raise RuntimeError("native probe process not found")
    process = max(candidates, key=lambda item: item.create_time())
    process.cpu_percent(None)
    rss: list[int] = []
    private: list[int] = []
    cpu: list[float] = []
    handles = threads = 0
    for _ in range(20):
        time.sleep(0.25)
        memory = process.memory_info()
        rss.append(memory.rss)
        private.append(getattr(memory, "private", memory.rss))
        cpu.append(process.cpu_percent(None))
        handles = max(handles, process.num_handles())
        threads = max(threads, process.num_threads())
    child.wait(timeout=5)
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scenario": "native_tk_full_window_probe",
        "ram_mb_avg": round(mean(rss) / 1_048_576, 3),
        "ram_mb_peak": round(max(rss) / 1_048_576, 3),
        "private_mb_avg": round(mean(private) / 1_048_576, 3),
        "cpu_percent_avg": round(mean(cpu), 3),
        "cpu_percent_peak": round(max(cpu), 3),
        "process_count": 1,
        "handles_peak": handles,
        "threads_peak": threads,
        "exit_code": child.returncode,
        "scope": "rendering feasibility only; no WebView, media, auth, or accessibility bridge",
    }
    output = ROOT / "benchmarks" / "frontend-native-probe.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
