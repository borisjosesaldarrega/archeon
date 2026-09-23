"""Controlled, privacy-safe ARCHI Vision benchmark for Desktop Agent M3."""

from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import psutil
from PIL import Image, ImageDraw

from archeon.core.paths import AppPaths
from archeon.vision import ArchiVisionProvider, VisionComponentManager


def fixture(kind: str) -> tuple[Image.Image, tuple[str, ...]]:
    image = Image.new("RGB", (1280, 800), "#f2f4f7")
    draw = ImageDraw.Draw(image)
    if kind in {"windows_dialog", "error"}:
        draw.rectangle((220, 130, 1060, 650), fill="white", outline="#555", width=3)
        draw.text((270, 190), "ARCHEON - Configuration Error", fill="#111")
        draw.text((270, 310), "Wake detector could not start.", fill="#b00020")
        draw.rectangle((790, 535, 980, 600), fill="#e5e7eb", outline="#444")
        draw.text((870, 557), "OK", fill="#111")
        return image, ("wake", "error", "ok")
    if kind == "accessible_app":
        draw.rectangle((80, 80, 1200, 720), fill="white", outline="#444")
        draw.text((130, 125), "Settings", fill="#111")
        for index, label in enumerate(("General", "Appearance", "Voice", "Privacy")):
            y = 220 + index * 90
            draw.rectangle((130, y, 430, y + 60), fill="#dbeafe", outline="#2563eb")
            draw.text((170, y + 20), label, fill="#111")
        return image, ("settings", "voice", "privacy")
    if kind == "custom_canvas":
        draw.ellipse((300, 160, 980, 740), fill="#071b26", outline="#00d8ff", width=8)
        draw.text((505, 330), "CUSTOM CANVAS", fill="#00e5ff")
        draw.rectangle((470, 440, 810, 535), fill="#00cfe8")
        draw.text((585, 475), "START", fill="#001018")
        return image, ("custom", "start")
    if kind == "chart":
        draw.text((80, 60), "Monthly latency (ms)", fill="#111")
        points = [(100 + i * 130, 650 - value * 4) for i, value in enumerate((50, 62, 41, 80, 55, 35, 29, 44))]
        draw.line(points, fill="#087ea4", width=8)
        for point in points:
            draw.ellipse((point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7), fill="#087ea4")
        return image, ("latency", "chart")
    if kind == "image":
        draw.rectangle((100, 100, 1180, 700), fill="#87ceeb")
        draw.ellipse((920, 150, 1040, 270), fill="#ffd54f")
        draw.polygon(((100, 700), (470, 250), (760, 700)), fill="#667c54")
        draw.text((490, 735), "Mountain landscape", fill="#111")
        return image, ("mountain", "landscape")
    if kind == "small_text":
        draw.text((70, 55), "System diagnostics", fill="#111")
        for row in range(28):
            draw.text((70, 100 + row * 22), f"service-{row:02d}  status=ready  latency={12 + row}ms", fill="#222")
        return image, ("diagnostics", "service")
    if kind == "webpage":
        draw.rectangle((0, 0, 1280, 90), fill="#1f2937")
        draw.text((80, 32), "https://docs.example.test/guide", fill="white")
        draw.text((100, 150), "ARCHEON User Guide", fill="#111")
        draw.text((100, 230), "Configure voice and privacy settings", fill="#333")
        draw.rectangle((100, 330, 350, 400), fill="#0ea5e9")
        draw.text((170, 355), "Continue", fill="white")
        return image, ("guide", "continue")
    if kind == "code":
        draw.rectangle((0, 0, 1280, 800), fill="#111827")
        lines = ("def start_agent():", "    state = load_state()", "    if state is None:",
                 "        raise RuntimeError('state missing')", "    return state.run()")
        for index, line in enumerate(lines, 1):
            draw.text((100, 100 + index * 70), f"{index:02d}  {line}", fill="#d1fae5")
        return image, ("runtimeerror", "state missing")
    if kind == "icons":
        labels = (("PLAY", "▶"), ("PAUSE", "Ⅱ"), ("SETTINGS", "⚙"), ("FAVORITE", "★"))
        for index, (label, glyph) in enumerate(labels):
            x = 100 + index * 290
            draw.ellipse((x, 250, x + 180, 430), fill="#082f49", outline="#00d8ff", width=4)
            draw.text((x + 76, 315), glyph, fill="white")
            draw.text((x + 50, 470), label, fill="#111")
        return image, ("play", "settings", "favorite")
    raise ValueError(kind)


class ResourceSampler:
    def __init__(self, provider: ArchiVisionProvider) -> None:
        self.provider = provider
        self.stop = threading.Event()
        self.peak_rss = 0
        self.last_rss = 0
        self.samples: list[float] = []
        self._tracked: psutil.Process | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.wait(0.1):
            process = self.provider._process
            if process is None or process.poll() is not None:
                continue
            try:
                if self._tracked is None or self._tracked.pid != process.pid:
                    self._tracked = psutil.Process(process.pid)
                    self._tracked.cpu_percent(interval=None)
                current = self._tracked
                rss = current.memory_info().rss + sum(
                    child.memory_info().rss for child in current.children(recursive=True)
                )
                self.peak_rss = max(self.peak_rss, rss)
                self.last_rss = rss
                self.samples.append(current.cpu_percent(interval=None))
            except (psutil.Error, OSError):
                pass

    def __enter__(self) -> "ResourceSampler":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop.set()
        self.thread.join(timeout=2)


def residues() -> list[int]:
    output: list[int] = []
    for process in psutil.process_iter(("pid", "name", "cmdline")):
        try:
            command = " ".join(process.info.get("cmdline") or []).casefold()
            if "llama-server" in (process.info.get("name") or "").casefold() and "archi-vision" in command:
                output.append(int(process.info["pid"]))
        except (psutil.Error, OSError):
            pass
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="run all ten corpus cases after size sweep")
    parser.add_argument("--one", action="store_true", help="run only the 640 px case")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/desktop-agent-m3-vision.json"))
    args = parser.parse_args()
    paths = AppPaths.discover()
    components = VisionComponentManager(paths.model_dir())
    provider = ArchiVisionProvider(
        paths.runtime_dir / "llama.cpp" / "llama-server.exe",
        components.artifact_path("language_model"), components.artifact_path("projector"),
        threads=max(1, min(6, (os.cpu_count() or 6) - 2)), idle_timeout_seconds=0,
    )
    atexit.register(provider.unload)
    cases = ["windows_dialog", "accessible_app", "custom_canvas", "error", "chart",
             "image", "small_text", "webpage", "code", "icons"]
    runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    initial_rss = psutil.Process().memory_info().rss
    initial_residues = residues()
    with ResourceSampler(provider) as resources:
        for max_side in ((640,) if args.one else (640, 960, 1280)):
            image, expected = fixture("error")
            encoded, size, preprocess_ms = provider.preprocess(image, max_side=max_side)
            image.close()
            started = time.perf_counter()
            try:
                observed = provider.analyze(
                    encoded, prompt="Identify the visible error and controls. Return concise structured JSON.",
                    image_size=size,
                )
            except Exception as error:
                failures.append({"context": f"error-{max_side}", "expected": list(expected),
                                 "actual": f"{type(error).__name__}: {error}", "category": "invalid_response"})
                runs.append({"case": "error", "max_side": max_side, "image_size": size,
                             "preprocess_ms": round(preprocess_ms, 3), "error": f"{type(error).__name__}: {error}"})
                continue
            body = " ".join((observed.window_summary, *observed.visible_text, *observed.errors)).casefold()
            matched = [word for word in expected if word in body]
            runs.append({"case": "error", "max_side": max_side, "image_size": size,
                         "preprocess_ms": round(preprocess_ms, 3), "wall_ms": round((time.perf_counter()-started)*1000, 3),
                         "matched": matched, "expected": list(expected), "observation": observed.public()})
        if args.full:
            for kind in cases:
                image, expected = fixture(kind)
                encoded, size, preprocess_ms = provider.preprocess(image, max_side=640)
                image.close()
                started = time.perf_counter()
                try:
                    observed = provider.analyze(encoded, prompt="Describe the interface and visible evidence concisely.", image_size=size)
                except Exception as error:
                    actual = f"{type(error).__name__}: {error}"
                    runs.append({"case": kind, "max_side": 640, "image_size": size,
                                 "preprocess_ms": round(preprocess_ms, 3), "error": actual})
                    failures.append({"context": kind, "expected": list(expected),
                                     "actual": actual, "category": "invalid_response"})
                    continue
                body = " ".join((observed.window_summary, *observed.visible_text, *observed.errors)).casefold()
                matched = [word for word in expected if word in body]
                run = {"case": kind, "max_side": 640, "image_size": size,
                       "preprocess_ms": round(preprocess_ms, 3), "wall_ms": round((time.perf_counter()-started)*1000, 3),
                       "matched": matched, "expected": list(expected), "observation": observed.public()}
                runs.append(run)
                if len(matched) < max(1, math.ceil(len(expected) / 2)):
                    failures.append({"context": kind, "expected": list(expected),
                                     "actual": observed.window_summary, "category": "semantic_miss"})
        peak_rss = resources.peak_rss
        settled_rss = resources.last_rss
        cpu_peak = max(resources.samples, default=0.0)
    unload_ms = provider.unload()
    time.sleep(0.5)
    final_rss = psutil.Process().memory_info().rss
    report = {
        "schema": 1, "benchmark": "Desktop Agent M3 ARCHI Vision", "backend": "cpu",
        "component": components.status(developer=True), "screenshots_persisted": False,
        "initial_residues": initial_residues, "runs": runs, "failure_cases": failures,
        "metrics": {"host_rss_before_mb": round(initial_rss/1048576, 3),
                    "runtime_peak_rss_mb": round(peak_rss/1048576, 3),
                    "runtime_settled_rss_mb": round(settled_rss/1048576, 3),
                    "sampled_cpu_peak_percent": round(cpu_peak, 3), "unload_ms": round(unload_ms, 3),
                    "gpu_backend": "unavailable_runtime_reports_no_devices",
                    "host_rss_after_mb": round(final_rss/1048576, 3), "residual_pids": residues()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"ok": not report["metrics"]["residual_pids"], "output": str(args.output),
                      "run_count": len(runs), "metrics": report["metrics"]}, ensure_ascii=False))
    return 0 if not report["metrics"]["residual_pids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
