"""Run isolated ARCHI Image Lite CPU/Vulkan benchmarks and emit honest metrics."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil


ROOT = Path.home() / "AppData" / "Local" / "ARCHEON"
MODEL = ROOT / "models" / "archi-image" / "lite" / "sdxs.safetensors"
RUNTIME = ROOT / "runtimes" / "archi-image"
OUTPUT = ROOT / "artifacts" / "M10" / "archi-image"
REPORT = Path(__file__).resolve().parents[1] / "benchmarks" / "ARCHI_IMAGE_LITE_M10.json"
EXPECTED_MODEL_SHA256 = "6cca5bfd11b588cdfb4602018c7e623d24c95fdfdc5ab2d4b9e6978b3186980f"
PROMPTS = (
    ("ARCHI_Image_Embryology", "clean educational illustration showing human embryology stages from fertilization to early fetus, chronological visual sequence, respectful medical textbook style, dark cyan accents, no labels, no text"),
    ("ARCHI_Image_Cybersecurity", "professional cybersecurity illustration, secure workstation protected by layered shields, network nodes and defensive monitoring, dark background with cyan light, clean composition, no text"),
    ("ARCHI_Image_General", "cinematic futuristic desktop assistant orb in a modest home office, elegant cyan lighting, realistic materials, balanced clean composition, no text, no watermark"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def executable(backend: str) -> Path:
    matches = sorted((RUNTIME / f"stable-diffusion.cpp-master-829-0a565f2-{backend}").rglob("sd-cli.exe"))
    if len(matches) != 1:
        raise RuntimeError(f"runtime_not_unique:{backend}:{len(matches)}")
    return matches[0]


def run_once(backend: str, name: str, prompt: str, seed: int) -> dict[str, object]:
    target = OUTPUT / backend / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    log_path = target.with_suffix(".log")
    command = [
        str(executable(backend)), "-m", str(MODEL), "-p", prompt,
        "-n", "words, letters, watermark, signature, distorted, blurry, duplicate",
        "--steps", "1", "--cfg-scale", "1", "--sampling-method", "euler",
        "--scheduler", "discrete", "-W", "512", "-H", "512", "-s", str(seed),
        "-o", str(target),
    ]
    if backend == "cpu":
        command += ["--backend", "cpu", "--threads", "6"]
    else:
        command += ["--backend", "vulkan0"]
    baseline_available = psutil.virtual_memory().available
    started = time.perf_counter()
    peak_rss = 0
    lowest_available = baseline_available
    cpu_seconds = 0.0
    with log_path.open("w", encoding="utf-8") as log:
        process = psutil.Popen(
            command, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        while process.poll() is None:
            processes = [process]
            try:
                processes.extend(process.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            current_rss = 0
            current_cpu = 0.0
            for item in processes:
                try:
                    current_rss += item.memory_info().rss
                    times = item.cpu_times(); current_cpu += times.user + times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak_rss = max(peak_rss, current_rss)
            cpu_seconds = max(cpu_seconds, current_cpu)
            lowest_available = min(lowest_available, psutil.virtual_memory().available)
            time.sleep(0.05)
        return_code = process.wait()
    elapsed = time.perf_counter() - started
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    runtime_match = re.search(r"generate_image completed in ([\d.]+)s", log_text)
    vram_match = re.search(r"total params memory size = [\d.]+MB \(VRAM ([\d.]+)MB, RAM ([\d.]+)MB\)", log_text)
    if return_code or not target.is_file():
        raise RuntimeError(f"generation_failed:{backend}:{name}:{return_code}")
    time.sleep(0.15)
    residue = [
        item.pid for item in psutil.process_iter(["pid", "name"])
        if str(item.info.get("name") or "").casefold() == "sd-cli.exe"
    ]
    return {
        "name": name, "seed": seed, "elapsed_ms": round(elapsed * 1000, 3),
        "runtime_generation_ms": round(float(runtime_match.group(1)) * 1000, 3) if runtime_match else None,
        "peak_process_rss_bytes": peak_rss,
        "system_available_memory_delta_bytes": max(0, baseline_available - lowest_available),
        "normalized_cpu_percent": round(cpu_seconds / max(elapsed, 0.001) / max(1, psutil.cpu_count()) * 100, 2),
        "reported_parameter_vram_mb": float(vram_match.group(1)) if vram_match else None,
        "reported_parameter_ram_mb": float(vram_match.group(2)) if vram_match else None,
        "peak_shared_gpu_memory_bytes": None,
        "output": str(target), "output_bytes": target.stat().st_size,
        "sha256": sha256(target), "residual_sd_cli_pids": residue,
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    actual_hash = sha256(MODEL)
    if actual_hash != EXPECTED_MODEL_SHA256:
        raise RuntimeError("model_hash_mismatch")
    backends: dict[str, object] = {}
    for backend in ("cpu", "vulkan"):
        runs = [run_once(backend, name, prompt, 4100 + index) for index, (name, prompt) in enumerate(PROMPTS)]
        backends[backend] = {
            "runs": runs,
            "average_elapsed_ms": round(sum(float(item["elapsed_ms"]) for item in runs) / len(runs), 3),
            "max_peak_process_rss_bytes": max(int(item["peak_process_rss_bytes"]) for item in runs),
            "process_cleanup_verified": all(not item["residual_sd_cli_pids"] for item in runs),
        }
    selected = min(backends, key=lambda name: float(backends[name]["average_elapsed_ms"]))
    for name, _prompt in PROMPTS:
        shutil.copy2(OUTPUT / selected / f"{name}.png", OUTPUT / f"{name}.png")
    report = {
        "schema_version": 1,
        "status": "BENCHMARKED_NOT_USER_VERIFIED",
        "visible_name": "ARCHI Image Lite",
        "candidate": "SDXS-512-DreamShaper",
        "model": {
            "path": str(MODEL), "bytes": MODEL.stat().st_size, "sha256": actual_hash,
            "source": "https://huggingface.co/akleine/sdxs-512/resolve/17ef024d73ebee1db9b0643f9c90454dae6c5772/sdxs.safetensors",
            "license_status": "CONDITIONAL_EVALUATION_ONLY_PENDING_DISTRIBUTION_REVIEW",
        },
        "runtime": {"name": "stable-diffusion.cpp", "commit": "0a565f2", "release": "master-829-0a565f2"},
        "generation": {"width": 512, "height": 512, "steps": 1, "cfg": 1, "sampler": "euler", "scheduler": "discrete"},
        "backends": backends, "selected_backend": selected,
        "upscaler": {"status": "NOT_YET_BENCHMARKED"},
        "limitations": [
            "Perceptual quality requires visual review; no metric is invented.",
            "Shared GPU peak is unavailable from this process sampler and remains null.",
            "Third-party consolidated safetensors needs final distribution/license provenance review.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "selected_backend": selected, "report": str(REPORT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
