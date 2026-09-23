"""Disposable llama.cpp multimodal provider for ARCHI Vision."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, RLock, Timer
from typing import Any

from .manager import VisionState


@dataclass(frozen=True, slots=True)
class SemanticScreenObservation:
    window_summary: str
    visible_text: tuple[str, ...] = ()
    controls: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()
    regions: tuple[dict[str, Any], ...] = ()
    possible_actions: tuple[str, ...] = ()
    confidence: float = 0.0
    method: str = "archi_vision"
    metrics: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return asdict(self)


class ArchiVisionProvider:
    def __init__(
        self, executable: Path, model_path: Path, projector_path: Path, *,
        threads: int = 6, context_size: int = 4096, startup_timeout_seconds: int = 180,
        backend: str = "cpu",
        idle_timeout_seconds: int = 60,
    ) -> None:
        self.executable = executable.resolve()
        self.model_path = model_path.resolve()
        self.projector_path = projector_path.resolve()
        self.threads = max(1, min(32, int(threads)))
        self.context_size = max(2048, min(8192, int(context_size)))
        self.startup_timeout_seconds = max(30, min(300, int(startup_timeout_seconds)))
        self.backend = backend
        self.idle_timeout_seconds = max(0, min(600, int(idle_timeout_seconds)))
        self.state = VisionState.UNLOADED
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int | None = None
        self._lock = RLock()
        self._cancel = Event()
        self._last_load_ms = 0.0
        self._cache_key: str | None = None
        self._cache_image_hash: str | None = None
        self._cache_value: SemanticScreenObservation | None = None
        self._idle_timer: Timer | None = None

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def load(self) -> float:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return 0.0
            for path in (self.executable, self.model_path, self.projector_path):
                if not path.is_file():
                    raise FileNotFoundError(path)
            self.state = VisionState.LOADING
            self._cancel.clear()
            self._port = self._free_port()
            command = [
                str(self.executable), "--model", str(self.model_path), "--mmproj", str(self.projector_path),
                "--host", "127.0.0.1", "--port", str(self._port), "--ctx-size", str(self.context_size),
                "--threads", str(self.threads), "--parallel", "1", "--no-webui", "--n-gpu-layers", "0",
                "--no-mmproj-offload", "--image-max-tokens", "1024",
            ]
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            started = time.perf_counter()
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags,
            )
            deadline = time.monotonic() + self.startup_timeout_seconds
            while time.monotonic() < deadline:
                if self._cancel.is_set():
                    self.unload()
                    raise RuntimeError("vision_cancelled")
                if self._process.poll() is not None:
                    code = self._process.returncode
                    self._process = None
                    self.state = VisionState.ERROR
                    raise RuntimeError(f"vision_runtime_exit:{code}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/health", timeout=0.4) as response:
                        if response.status == 200:
                            self._last_load_ms = (time.perf_counter() - started) * 1000
                            self.state = VisionState.READY
                            return self._last_load_ms
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            self.unload()
            self.state = VisionState.ERROR
            raise TimeoutError("vision_runtime_start_timeout")

    def analyze(self, image_bytes: bytes, *, prompt: str, image_size: tuple[int, int]) -> SemanticScreenObservation:
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        cache_key = hashlib.sha256(image_bytes + b"\0" + prompt.encode()).hexdigest()
        reusable_grounding = bool(
            self._cache_value is not None
            and any(isinstance(item, dict) and item.get("bounds") for item in self._cache_value.controls)
        )
        if self._cache_value is not None and (
            cache_key == self._cache_key or (image_hash == self._cache_image_hash and reusable_grounding)
        ):
            cached = self._cache_value.public()
            cached["metrics"] = {**cached["metrics"], "cache_hit": True}
            return SemanticScreenObservation(**cached)
        load_ms = self.load()
        assert self._port is not None
        self.state = VisionState.BUSY
        inference_started = time.perf_counter()
        schema_instruction = (
            "Return JSON only with keys window_summary, visible_text, controls, errors, regions, "
            "possible_actions, confidence. controls and regions use normalized [x1,y1,x2,y2] bounds "
            "from 0 to 1. Do not invent unreadable controls. " + prompt
        )
        payload = {
            "model": "ARCHI Vision",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": schema_instruction},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii"),
                }},
            ]}],
            "max_tokens": 700, "temperature": 0.0, "stream": True,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/v1/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            fragments: list[str] = []
            first_token_ms: float | None = None
            with urllib.request.urlopen(request, timeout=300) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    value_text = line[5:].strip()
                    if value_text == "[DONE]":
                        break
                    event = json.loads(value_text)
                    fragment = str(event.get("choices", [{}])[0].get("delta", {}).get("content") or "")
                    if fragment:
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - inference_started) * 1000
                        fragments.append(fragment)
            text = "".join(fragments)
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise ValueError("vision_response_not_structured")
            value = json.loads(match.group(0))
            observation = SemanticScreenObservation(
                window_summary=str(value.get("window_summary", ""))[:2000],
                visible_text=self._text_items(value.get("visible_text"), limit=100, width=1000),
                controls=self._grounded_items(value.get("controls"), limit=100),
                errors=self._text_items(value.get("errors"), limit=50, width=1000),
                regions=self._grounded_items(value.get("regions"), limit=100),
                possible_actions=self._text_items(value.get("possible_actions"), limit=50, width=500),
                confidence=self._confidence(value.get("confidence")),
                metrics={
                    "load_ms": round(load_ms, 3),
                    "first_token_ms": round(first_token_ms, 3) if first_token_ms is not None else None,
                    "inference_ms": round((time.perf_counter() - inference_started) * 1000, 3),
                    "input_width": image_size[0], "input_height": image_size[1], "cache_hit": False,
                },
            )
            self._cache_key, self._cache_image_hash, self._cache_value = cache_key, image_hash, observation
            return observation
        finally:
            if self._cancel.is_set():
                self.state = VisionState.UNLOADED
            elif self.state is not VisionState.ERROR:
                self.state = VisionState.READY
                self._arm_idle_unload()

    @staticmethod
    def _text_items(value: Any, *, limit: int, width: int) -> tuple[str, ...]:
        if isinstance(value, str):
            source: list[Any] = value.splitlines()
        elif isinstance(value, list):
            source = value
        elif value is None:
            source = []
        else:
            source = [value]
        output: list[str] = []
        for item in source[:limit]:
            if isinstance(item, dict):
                item = item.get("text") or item.get("message") or item.get("action") or item.get("name") or ""
            text = " ".join(str(item).split())[:width]
            if text:
                output.append(text)
        return tuple(output)

    @staticmethod
    def _grounded_items(value: Any, *, limit: int) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        output: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            cleaned = {str(key)[:80]: entry for key, entry in item.items() if key != "bounds"}
            bounds = item.get("bounds")
            numeric = (
                [float(point) for point in bounds]
                if isinstance(bounds, list) and len(bounds) == 4
                and all(isinstance(point, (int, float)) for point in bounds)
                else []
            )
            if numeric and all(0.0 <= point <= 1.0 for point in numeric):
                cleaned["bounds"] = [round(point, 6) for point in numeric]
                cleaned["grounding_scale"] = "normalized_1"
            elif numeric and all(0.0 <= point <= 1000.0 for point in numeric):
                cleaned["bounds"] = [round(point / 1000.0, 6) for point in numeric]
                cleaned["grounding_scale"] = "normalized_1000"
            else:
                cleaned["grounding_valid"] = False
            normalized = cleaned.get("bounds", [])
            if normalized and not (normalized[0] < normalized[2] and normalized[1] < normalized[3]):
                cleaned.pop("bounds", None)
                cleaned.pop("grounding_scale", None)
                cleaned["grounding_valid"] = False
            output.append(cleaned)
        return tuple(output)

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def preprocess(image: Any, *, max_side: int) -> tuple[bytes, tuple[int, int], float]:
        started = time.perf_counter()
        bounded = max(320, min(1600, int(max_side)))
        working = image.convert("RGB")
        if max(working.size) > bounded:
            scale = bounded / max(working.size)
            working = working.resize(
                (max(1, round(working.width * scale)), max(1, round(working.height * scale))),
            )
        output = io.BytesIO()
        working.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue(), working.size, (time.perf_counter() - started) * 1000

    def invalidate_cache(self) -> None:
        self._cache_key = None
        self._cache_image_hash = None
        self._cache_value = None

    def cancel(self) -> None:
        self._cancel.set()
        self.unload()

    def unload(self) -> float:
        started = time.perf_counter()
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            process = self._process
            if process is None:
                self.state = VisionState.UNLOADED
                return 0.0
            self.state = VisionState.UNLOADING
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=10, check=False,
                        )
                    else:
                        process.kill()
                    process.wait(timeout=5)
            self._process = None
            self._port = None
            self.state = VisionState.UNLOADED
        return (time.perf_counter() - started) * 1000

    def _arm_idle_unload(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self.idle_timeout_seconds:
            self._idle_timer = Timer(self.idle_timeout_seconds, self.unload)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def status(self, *, developer: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": "ARCHI Vision", "state": self.state.value,
            "loaded": self._process is not None and self._process.poll() is None,
        }
        if developer:
            value.update({"backend": self.backend, "pid": self._process.pid if self._process else None,
                          "last_load_ms": round(self._last_load_ms, 3)})
        return value
