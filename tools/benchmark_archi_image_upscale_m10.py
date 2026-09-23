"""Benchmark the optional Real-ESRGAN NCNN Vulkan sidecar and update M10 evidence."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import time
from pathlib import Path

import psutil


ROOT = Path.home() / "AppData" / "Local" / "ARCHEON"
ARTIFACTS = ROOT / "artifacts" / "M10" / "archi-image"
RUNTIME_DIR = ROOT / "runtimes" / "archi-image" / "realesrgan-ncnn-vulkan-20220424"
RUNTIME = RUNTIME_DIR / "realesrgan-ncnn-vulkan.exe"
SOURCE = ARTIFACTS / "ARCHI_Image_Embryology.png"
OUTPUT = ARTIFACTS / "ARCHI_Image_Embryology_1024.png"
REPORT = Path(__file__).resolve().parents[1] / "benchmarks" / "ARCHI_IMAGE_LITE_M10.json"
EXPECTED_RUNTIME_SHA256 = "ABC02804E17982A3BE33675E4D471E91EA374E65B70167ABC09E31ACB412802D"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as source:
        header = source.read(24)
    if not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("upscale_output_not_png")
    return struct.unpack(">II", header[16:24])


def main() -> int:
    if not RUNTIME.is_file() or not SOURCE.is_file() or not REPORT.is_file():
        raise RuntimeError("upscale_component_or_source_missing")
    OUTPUT.unlink(missing_ok=True)
    baseline = psutil.virtual_memory().available
    lowest_available = baseline
    peak_rss = 0
    cpu_seconds = 0.0
    command = [
        str(RUNTIME), "-i", str(SOURCE), "-o", str(OUTPUT), "-s", "2",
        "-t", "128", "-m", str(RUNTIME_DIR / "models"), "-n", "realesr-animevideov3",
        "-g", "0", "-j", "1:2:1", "-f", "png",
    ]
    started = time.perf_counter()
    process = psutil.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    while process.poll() is None:
        try:
            peak_rss = max(peak_rss, process.memory_info().rss)
            times = process.cpu_times(); cpu_seconds = max(cpu_seconds, times.user + times.system)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        lowest_available = min(lowest_available, psutil.virtual_memory().available)
        time.sleep(0.025)
    log = (process.stdout.read() if process.stdout else b"").decode("utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    if process.returncode or not OUTPUT.is_file() or "failed" in log.casefold():
        raise RuntimeError(f"upscale_failed:{process.returncode}")
    width, height = png_dimensions(OUTPUT)
    if (width, height) != (1024, 1024):
        raise RuntimeError("upscale_dimensions_invalid")
    time.sleep(0.15)
    residual = [item.pid for item in psutil.process_iter(["pid", "name"]) if str(item.info.get("name") or "").casefold() == RUNTIME.name.casefold()]
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report["upscaler"] = {
        "status": "BENCHMARKED_NOT_USER_VERIFIED", "name": "Real-ESRGAN NCNN Vulkan",
        "source": "https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0",
        "release_archive_sha256": EXPECTED_RUNTIME_SHA256,
        "scale": 2, "input": str(SOURCE), "output": str(OUTPUT),
        "output_bytes": OUTPUT.stat().st_size, "output_sha256": sha256(OUTPUT),
        "width": width, "height": height, "elapsed_ms": round(elapsed * 1000, 3),
        "peak_process_rss_bytes": peak_rss,
        "system_available_memory_delta_bytes": max(0, baseline - lowest_available),
        "normalized_cpu_percent": round(cpu_seconds / max(elapsed, .001) / max(1, psutil.cpu_count()) * 100, 2),
        "residual_process_pids": residual, "process_cleanup_verified": not residual,
        "ffmpeg_required": False,
        "quality_note": "Improves edge resolution only; it does not repair anatomy, text, or semantic mistakes.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "upscaler": report["upscaler"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
