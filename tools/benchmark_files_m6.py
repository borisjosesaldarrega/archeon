"""Packaged M6 resource, language-repair latency and residue benchmark."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist-files-m6" / "Archeo32n" / "Archeo32n.exe"
sys.path.insert(0, str(ROOT / "src"))


def sample(process: psutil.Process) -> dict[str, float | int]:
    process.cpu_percent(None)
    time.sleep(0.35)
    tree = [process, *process.children(recursive=True)]
    living = [item for item in tree if item.is_running()]
    return {
        "rss_mib": round(sum(item.memory_info().rss for item in living) / 1024 / 1024, 3),
        "cpu_percent": round(sum(item.cpu_percent(None) for item in living), 3),
        "processes": len(living),
        "threads": sum(item.num_threads() for item in living),
    }


def run_case(data: Path, *, artifacts: bool) -> dict[str, object]:
    args = [str(EXE), "--headless", "--auto-exit", "3", "--allow-multiple", "--data-dir", str(data)]
    if artifacts:
        args.append("--benchmark-desktop-m4")
    started = time.perf_counter()
    process = subprocess.Popen(args, creationflags=0x08000000)
    tracked = psutil.Process(process.pid)
    report_path = data / "desktop-agent-m4-smoke.json"
    deadline = time.monotonic() + 2.2
    while time.monotonic() < deadline and artifacts and not report_path.exists():
        time.sleep(0.05)
    time.sleep(1.2 if not artifacts else 0.55)
    resources = sample(tracked)
    children = [item.pid for item in tracked.children(recursive=True)]
    exit_code = process.wait(timeout=8)
    time.sleep(0.2)
    return {
        "resources": resources,
        "exit_code": exit_code,
        "residual_children": [pid for pid in children if psutil.pid_exists(pid)],
        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        "smoke": json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None,
    }


def repair_latency() -> dict[str, float | int]:
    from archeon.understanding import NaturalLanguageRepair

    repair = NaturalLanguageRepair()
    samples = [
        "has un wor con el resumen y pasalo a pe de efe",
        "lee eso y ponlo mas natural no tan ia",
        "borra ese archivo",
        "toma cap de la pagina y ponla al inicio",
    ]
    elapsed: list[float] = []
    for index in range(2000):
        started = time.perf_counter_ns()
        repair.interpret(samples[index % len(samples)], known_files=("informe.docx",))
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000)
    elapsed.sort()
    return {
        "iterations": len(elapsed),
        "median_ms": round(statistics.median(elapsed), 4),
        "p95_ms": round(elapsed[int(len(elapsed) * 0.95) - 1], 4),
        "max_ms": round(max(elapsed), 4),
    }


def main() -> int:
    if not EXE.exists():
        raise FileNotFoundError(EXE)
    with tempfile.TemporaryDirectory(prefix="archeon-m6-idle-") as idle_dir, tempfile.TemporaryDirectory(prefix="archeon-m6-artifacts-") as artifact_dir:
        idle = run_case(Path(idle_dir), artifacts=False)
        artifacts = run_case(Path(artifact_dir), artifacts=True)
    files = [item for item in EXE.parent.rglob("*") if item.is_file()]
    report = {
        "milestone": "Files/Documents M6",
        "packaged": True,
        "build": {
            "path": str(EXE),
            "bytes": sum(item.stat().st_size for item in files),
            "files": len(files),
            "gguf": sum(item.suffix.casefold() == ".gguf" for item in files),
            "ffmpeg": sum("ffmpeg" in item.name.casefold() or "avcodec" in item.name.casefold() for item in files),
        },
        "idle": idle,
        "artifact_loaded": artifacts,
        "natural_language_repair": repair_latency(),
    }
    target = ROOT / "benchmarks" / "files-documents-m6-packaged.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    valid = idle["exit_code"] == artifacts["exit_code"] == 0 and artifacts["smoke"] and artifacts["smoke"]["ok"]
    return 0 if valid and not idle["residual_children"] and not artifacts["residual_children"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
