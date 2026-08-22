"""Repeatable ARCHEON process-tree benchmark for Windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import psutil


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks"


def family(root: psutil.Process) -> list[psutil.Process]:
    try:
        candidates = [root, *root.children(recursive=True)]
        return [process for process in candidates if process.is_running()]
    except psutil.NoSuchProcess:
        return []


def measure(name: str, extra: list[str], *, warmup: float, sample: float) -> dict[str, object]:
    runtime = ROOT / f".runtime-benchmark-{name}"
    command = [
        sys.executable,
        "-m",
        "archeon",
        *extra,
        "--auto-exit",
        str(warmup + sample + 3.0),
        "--data-dir",
        str(runtime),
    ]
    wall_started = time.perf_counter()
    child = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert child.stdout is not None
    ready = json.loads(child.stdout.readline())
    # On Windows a venv executable can be a short-lived launcher. ARCHEON
    # announces the real interpreter PID so descendants (including WebView2)
    # are attributed to the application instead of the launcher.
    root = psutil.Process(int(ready["pid"]))
    ui_ready_ms: float | None = None
    deadline = time.perf_counter() + warmup
    while time.perf_counter() < deadline and root.is_running():
        names = {process.name().lower() for process in family(root)}
        if ui_ready_ms is None and any("webview2" in item for item in names):
            ui_ready_ms = (time.perf_counter() - wall_started) * 1000
        time.sleep(0.05)

    processes = family(root)
    known = {process.pid: process for process in processes}
    for process in known.values():
        try:
            process.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    samples: list[float] = []
    rss_samples: list[int] = []
    private_samples: list[int] = []
    sample_deadline = time.perf_counter() + sample
    while time.perf_counter() < sample_deadline and root.is_running():
        time.sleep(min(0.25, max(0.01, sample_deadline - time.perf_counter())))
        current = family(root)
        for process in current:
            known.setdefault(process.pid, process)
        rss = 0
        private = 0
        cpu = 0.0
        for process in known.values():
            try:
                memory = process.memory_info()
                rss += memory.rss
                private += getattr(memory, "private", memory.rss)
                cpu += process.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rss_samples.append(rss)
        private_samples.append(private)
        samples.append(cpu)

    process_names = sorted(process.name() for process in family(root))
    stdout_tail, stderr = child.communicate(timeout=8)
    log_path = runtime / "logs" / "archeon.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return {
        "scenario": name,
        "core_startup_ms": ready["startup_ms"],
        "ui_process_ready_ms": round(ui_ready_ms, 3) if ui_ready_ms is not None else None,
        "ram_idle_mb_avg": round(mean(rss_samples) / 1_048_576, 3),
        "ram_idle_mb_peak": round(max(rss_samples) / 1_048_576, 3),
        "private_memory_mb_avg": round(mean(private_samples) / 1_048_576, 3),
        "private_memory_mb_peak": round(max(private_samples) / 1_048_576, 3),
        "cpu_idle_percent_avg": round(mean(samples), 3),
        "cpu_idle_percent_peak": round(max(samples), 3),
        "process_count": len(process_names),
        "process_names": process_names,
        "music_started_confirmed": (
            "music.started" in log_text
            or ('"event":"archeon.benchmark.music","ok":true' in stdout_tail)
        ) if "music" in name else None,
        "gpu_percent": None,
        "gpu_note": "Per-process GPU counters are unavailable through psutil on this host.",
        "exit_code": child.returncode,
        "stderr": stderr.strip(),
        "stdout_tail": stdout_tail.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=float, default=3.0)
    parser.add_argument("--sample", type=float, default=3.0)
    parser.add_argument("--scenarios", nargs="+", choices=("headless", "main", "ghost", "ghost_music", "music"))
    args = parser.parse_args()
    scenarios = {
        "headless": ["--headless"],
        "main": [],
        "ghost": ["--ghost"],
        "ghost_music": ["--ghost", "--benchmark-music"],
        "music": ["--benchmark-music"],
    }
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "executable": str(sys.executable),
        "scenarios": [
            measure(name, scenarios[name], warmup=args.warmup, sample=args.sample)
            for name in (args.scenarios or list(scenarios))
        ],
    }
    RESULTS.mkdir(exist_ok=True)
    latest = RESULTS / "latest.json"
    latest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    with (RESULTS / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
