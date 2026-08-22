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


def gpu_utilization(processes: list[psutil.Process]) -> tuple[float | None, str]:
    """Take one bounded Windows GPU Engine sample for the ARCHEON process tree."""
    if sys.platform != "win32" or not processes:
        return None, "Windows GPU Engine counters are unavailable on this platform."
    pids = ",".join(str(process.pid) for process in processes)
    script = (
        f"$targetPids=@({pids});"
        "$total=0.0;"
        "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -MaxSamples 1 -ErrorAction Stop).CounterSamples|"
        "ForEach-Object{if($_.InstanceName -match 'pid_(\\d+)_' -and $targetPids -contains [int]$Matches[1]){$total+=$_.CookedValue}};"
        "$total|ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=8, check=True,
        )
        return round(float(json.loads(result.stdout)), 3), "One Windows GPU Engine sample; summed across ARCHEON engines."
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        return None, "Windows GPU Engine counters could not be sampled on this host."


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
        "--allow-multiple",
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

    final_family = family(root)
    gpu_percent, gpu_note = gpu_utilization(final_family)
    process_names = sorted(process.name() for process in final_family)
    process_details = []
    for process in final_family:
        try:
            memory = process.memory_info()
            command_line = " ".join(process.cmdline())
            process_details.append({
                "name": process.name(),
                "role": next((part.split("=", 1)[1] for part in process.cmdline() if part.startswith("--type=")), "main"),
                "private_mb": round(getattr(memory, "private", memory.rss) / 1_048_576, 3),
                "rss_mb": round(memory.rss / 1_048_576, 3),
                "webview": "msedgewebview2" in command_line.casefold(),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    stdout_tail, stderr = child.communicate(timeout=8)
    benchmark_events = []
    for line in stdout_tail.splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict) and str(value.get("event", "")).startswith("archeon.benchmark."):
                benchmark_events.append(value)
        except json.JSONDecodeError:
            pass
    launcher_event = next((item for item in benchmark_events if item.get("event") == "archeon.benchmark.launcher"), None)
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
        "process_details": process_details,
        "launcher_scan_ms": launcher_event.get("scan_ms") if launcher_event else None,
        "launcher_items": launcher_event.get("items") if launcher_event else None,
        "music_started_confirmed": (
            "music.started" in log_text
            or ('"event":"archeon.benchmark.music","ok":true' in stdout_tail)
        ) if "music" in name else None,
        "gpu_percent": gpu_percent,
        "gpu_note": gpu_note,
        "exit_code": child.returncode,
        "stderr": stderr.strip(),
        "stdout_tail": stdout_tail.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=float, default=3.0)
    parser.add_argument("--sample", type=float, default=3.0)
    parser.add_argument("--scenarios", nargs="+", choices=(
        "headless", "main", "full_ui", "ghost", "ghost_radial", "ghost_music",
        "music", "launcher", "background_image", "background_video",
    ))
    args = parser.parse_args()
    scenarios = {
        "headless": ["--headless"],
        "main": [],
        "full_ui": ["--benchmark-guest"],
        "ghost": ["--ghost"],
        "ghost_radial": ["--ghost", "--benchmark-radial"],
        "ghost_music": ["--ghost", "--benchmark-music"],
        "music": ["--benchmark-guest", "--benchmark-music"],
        "launcher": ["--headless", "--benchmark-launcher"],
        "background_image": ["--benchmark-guest", "--benchmark-background", "image"],
        "background_video": ["--benchmark-guest", "--benchmark-background", "video"],
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
