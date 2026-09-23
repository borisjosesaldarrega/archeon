"""Packaged files/documents iteration resource, lazy-load and residue benchmark."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist-files-m5" / "Archeo32n" / "Archeo32n.exe"


def sample(process: psutil.Process) -> dict[str, float | int]:
    process.cpu_percent(None); time.sleep(0.35)
    tree = [process, *process.children(recursive=True)]
    living = [item for item in tree if item.is_running()]
    return {
        "rss_mib": round(sum(item.memory_info().rss for item in living) / 1024 / 1024, 3),
        "cpu_percent": round(sum(item.cpu_percent(None) for item in living), 3),
        "processes": len(living), "threads": sum(item.num_threads() for item in living),
    }


def run_case(data: Path, *, artifacts: bool) -> dict[str, object]:
    args = [str(EXE), "--headless", "--auto-exit", "3", "--allow-multiple", "--data-dir", str(data)]
    if artifacts: args.append("--benchmark-desktop-m4")
    started = time.perf_counter()
    process = subprocess.Popen(args, creationflags=0x08000000)
    tracked = psutil.Process(process.pid)
    report_path = data / "desktop-agent-m4-smoke.json"
    deadline = time.monotonic() + 2.2
    while time.monotonic() < deadline and artifacts and not report_path.exists(): time.sleep(0.05)
    time.sleep(1.2 if not artifacts else 0.55)
    resources = sample(tracked)
    children = [item.pid for item in tracked.children(recursive=True)]
    exit_code = process.wait(timeout=8); time.sleep(0.2)
    return {
        "resources": resources, "exit_code": exit_code,
        "residual_children": [pid for pid in children if psutil.pid_exists(pid)],
        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        "smoke": json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="archeon-files-idle-") as idle_dir, tempfile.TemporaryDirectory(prefix="archeon-files-artifacts-") as artifact_dir:
        idle = run_case(Path(idle_dir), artifacts=False)
        artifacts = run_case(Path(artifact_dir), artifacts=True)
    files = [item for item in EXE.parent.rglob("*") if item.is_file()]
    report = {
        "milestone": "Files/Documents M5", "packaged": True,
        "build": {"path": str(EXE), "bytes": sum(item.stat().st_size for item in files), "files": len(files),
                  "gguf": sum(item.suffix.casefold() == ".gguf" for item in files),
                  "ffmpeg": sum("ffmpeg" in item.name.casefold() or "avcodec" in item.name.casefold() for item in files)},
        "idle": idle, "artifact_loaded": artifacts,
    }
    target = ROOT / "benchmarks" / "files-documents-m5-packaged.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    valid = idle["exit_code"] == artifacts["exit_code"] == 0 and artifacts["smoke"] and artifacts["smoke"]["ok"]
    return 0 if valid and not idle["residual_children"] and not artifacts["residual_children"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
