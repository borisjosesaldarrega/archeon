"""Local llama.cpp provider isolated in a disposable subprocess."""

from __future__ import annotations

import json
import hashlib
import os
import socket
import subprocess
import time
import re
import urllib.error
import urllib.request
from pathlib import Path
from threading import RLock, Timer
from typing import Any, Protocol

from .models import GenerationRequest, GenerationResult, ModelDescriptor, ModelState
from .resources import MemoryPressureGuard


class ModelProvider(Protocol):
    @property
    def state(self) -> ModelState: ...
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
    def unload(self) -> None: ...
    def status(self) -> dict[str, Any]: ...


class LlamaCppProvider:
    """Start llama-server only for inference and terminate it after idle timeout."""

    def __init__(
        self,
        executable: Path,
        model_path: Path,
        descriptor: ModelDescriptor,
        *,
        context_size: int = 4096,
        threads: int = 6,
        idle_timeout_seconds: int = 120,
        startup_timeout_seconds: int = 120,
        backend: str = "cpu",
        pressure_guard: MemoryPressureGuard | None = None,
    ) -> None:
        self.executable = executable.resolve()
        self.model_path = model_path.resolve()
        self.descriptor = descriptor
        self.context_size = max(512, min(32768, int(context_size)))
        self.threads = max(1, min(64, int(threads)))
        self.idle_timeout_seconds = max(0, min(3600, int(idle_timeout_seconds)))
        self.startup_timeout_seconds = max(10, min(300, int(startup_timeout_seconds)))
        self.backend = backend
        self.pressure_guard = pressure_guard
        self._state = ModelState.UNLOADED
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int | None = None
        self._timer: Timer | None = None
        self._lock = RLock()
        self._last_error: str | None = None
        self._last_load_ms = 0.0
        self._integrity_verified = False

    @property
    def state(self) -> ModelState:
        with self._lock:
            if self._process is not None and self._process.poll() is not None:
                self._process = None
                self._port = None
                if self._state is ModelState.READY:
                    self._state = ModelState.ERROR
                    self._last_error = "llama_server_exited"
            return self._state

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _start_server(self) -> float:
        if self.state is ModelState.READY:
            return 0.0
        if not self.executable.is_file():
            raise FileNotFoundError("llama_server_missing")
        if not self.model_path.is_file():
            raise FileNotFoundError("local_model_missing")
        if self.pressure_guard is not None:
            self.pressure_guard.prepare()
        self._verify_model()
        self._state = ModelState.LOADING
        self._last_error = None
        started = time.perf_counter()
        port = self._free_port()
        command = [
            str(self.executable), "--model", str(self.model_path), "--host", "127.0.0.1",
            "--port", str(port), "--ctx-size", str(self.context_size), "--threads", str(self.threads),
            "--parallel", "1", "--no-webui", "--jinja", "--reasoning-format", "none",
        ]
        if self.backend == "cpu":
            command.extend(("--n-gpu-layers", "0"))
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=creationflags,
        )
        self._port = port
        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self._state = ModelState.ERROR
                self._last_error = f"llama_server_exit:{self._process.returncode}"
                raise RuntimeError(self._last_error)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    if response.status == 200:
                        self._last_load_ms = (time.perf_counter() - started) * 1000
                        self._state = ModelState.READY
                        return self._last_load_ms
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        self.unload()
        self._state = ModelState.ERROR
        self._last_error = "llama_server_start_timeout"
        raise TimeoutError(self._last_error)

    def _verify_model(self) -> None:
        if self._integrity_verified:
            return
        stat = self.model_path.stat()
        if stat.st_size != self.descriptor.size_bytes:
            raise ValueError("model_size_mismatch")
        receipt_path = self.model_path.with_name(f".{self.model_path.name}.verified.json")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            receipt = {}
        if (
            receipt.get("sha256") == self.descriptor.sha256
            and receipt.get("size_bytes") == stat.st_size
            and receipt.get("mtime_ns") == stat.st_mtime_ns
        ):
            self._integrity_verified = True
            return
        digest = hashlib.sha256()
        with self.model_path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != self.descriptor.sha256:
            raise ValueError("model_sha256_mismatch")
        self._integrity_verified = True
        receipt = {
            "schema_version": 1,
            "sha256": self.descriptor.sha256,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        try:
            temporary = receipt_path.with_suffix(receipt_path.suffix + f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(receipt, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, receipt_path)
        except OSError:
            # Read-only model directories remain supported; they simply re-verify next process.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _arm_idle_unload(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        if self.idle_timeout_seconds:
            self._timer = Timer(self.idle_timeout_seconds, self.unload)
            self._timer.daemon = True
            self._timer.start()

    def generate(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        marks: dict[str, float] = {"request_started": started}
        with self._lock:
            reported_load_ms = self._start_server()
            marks["server_ready"] = time.perf_counter()
            load_ms = (marks["server_ready"] - started) * 1000 if reported_load_ms else 0.0
            assert self._port is not None
            payload: dict[str, Any] = {
                "model": self.descriptor.id,
                "messages": list(request.messages),
                "max_tokens": max(1, min(4096, int(request.max_tokens))),
                "temperature": max(0.0, min(2.0, float(request.temperature))),
                "stream": True,
                "stream_options": {"include_usage": True},
                "chat_template_kwargs": {"enable_thinking": bool(request.enable_thinking)},
            }
            if request.response_format:
                payload["response_format"] = dict(request.response_format)
            http_request = urllib.request.Request(
                f"http://127.0.0.1:{self._port}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            marks["payload_ready"] = time.perf_counter()
            server_timings: dict[str, Any] = {}
            try:
                marks["request_sent"] = time.perf_counter()
                with urllib.request.urlopen(http_request, timeout=300) as response:
                    marks["headers_received"] = time.perf_counter()
                    parts: list[str] = []
                    usage: dict[str, Any] = {}
                    first_token_ms: float | None = None
                    for raw_line in response:
                        marks.setdefault("first_stream_event", time.perf_counter())
                        line = raw_line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue
                        body = line[5:].strip()
                        if body == "[DONE]":
                            break
                        chunk = json.loads(body)
                        if isinstance(chunk.get("timings"), dict):
                            server_timings.update(chunk["timings"])
                        if isinstance(chunk.get("usage"), dict):
                            usage = chunk["usage"]
                        choices = chunk.get("choices") or []
                        content = choices[0].get("delta", {}).get("content") if choices else None
                        if content:
                            if first_token_ms is None:
                                marks["first_content"] = time.perf_counter()
                                first_token_ms = (marks["first_content"] - started) * 1000
                            parts.append(str(content))
                            if request.on_token is not None:
                                request.on_token(str(content))
            except Exception as error:
                self._last_error = f"inference_failed:{type(error).__name__}"
                raise
            finally:
                self._arm_idle_unload()
        text = "".join(parts).strip()
        text = re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        completed = time.perf_counter()
        timings = {
            "server_start_ms": round((marks["server_ready"] - started) * 1000, 3),
            "llama_startup_ms": round(reported_load_ms, 3),
            "integrity_and_startup_overhead_ms": round(max(0.0, load_ms - reported_load_ms), 3),
            "request_preparation_ms": round((marks["payload_ready"] - marks["server_ready"]) * 1000, 3),
            "http_wait_ms": round((marks.get("headers_received", completed) - marks["request_sent"]) * 1000, 3),
            "stream_to_first_content_ms": round(
                (marks.get("first_content", completed) - marks.get("headers_received", completed)) * 1000, 3
            ),
            "generation_after_first_content_ms": round(
                (completed - marks.get("first_content", completed)) * 1000, 3
            ),
            "first_stream_event_ms": round(
                (marks.get("first_stream_event", completed) - started) * 1000, 3
            ),
            "server": server_timings,
        }
        return GenerationResult(
            text=text, model_id=self.descriptor.id,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            load_ms=load_ms, first_token_ms=first_token_ms,
            total_ms=(completed - started) * 1000,
            timings=timings,
        )

    def unload(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            process = self._process
            if process is None:
                self._state = ModelState.UNLOADED
                return
            self._state = ModelState.UNLOADING
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self._process = None
            self._port = None
            self._state = ModelState.UNLOADED

    def status(self) -> dict[str, Any]:
        return {
            "provider": "llama.cpp", "state": self.state.value,
            "model_id": self.descriptor.id, "model_path": str(self.model_path),
            "backend": self.backend, "context_size": self.context_size,
            "threads": self.threads, "idle_timeout_seconds": self.idle_timeout_seconds,
            "pid": self._process.pid if self._process and self._process.poll() is None else None,
            "last_load_ms": round(self._last_load_ms, 3), "last_error": self._last_error,
            "memory_pressure": self.pressure_guard.status() if self.pressure_guard else None,
        }
