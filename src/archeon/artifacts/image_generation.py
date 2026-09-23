"""Optional, provider-based image generation without an idle resident model."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol


class ImageProviderState(StrEnum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    UNLOADED = "unloaded"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ImageRequest:
    prompt: str
    output_path: Path
    width: int = 768
    height: int = 768
    locale: str = "es"
    negative_prompt: str = ""
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class ImageResult:
    ok: bool
    provider: str
    state: str
    path: str | None = None
    width: int = 0
    height: int = 0
    sha256: str | None = None
    elapsed_ms: float = 0.0
    error: str | None = None

    def public(self) -> dict[str, object]:
        return asdict(self)


class ImageGenerationProvider(Protocol):
    def status(self) -> dict[str, object]: ...
    def generate(self, request: ImageRequest) -> ImageResult: ...
    def unload(self) -> None: ...


class ImageUpscaleProvider(Protocol):
    def status(self) -> dict[str, object]: ...
    def upscale(self, source: Path, output: Path, *, scale: int = 2) -> ImageResult: ...


def _available_memory_bytes() -> int:
    """Read available RAM without adding psutil to the base application."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended", ctypes.c_ulonglong),
            ]
        status = MemoryStatus(); status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.avail_phys)
    return 0


class ModelResourceManager:
    """Admission/lifecycle guard; it never downloads or keeps a worker alive."""

    def __init__(self, component_dir: Path, *, minimum_free_bytes: int, memory_reader: Callable[[], int] = _available_memory_bytes) -> None:
        self.component_dir = component_dir.expanduser().resolve()
        self.minimum_free_bytes = max(0, int(minimum_free_bytes))
        self._memory_reader = memory_reader
        self.loaded = False

    def admit(self) -> tuple[bool, str | None]:
        available = self._memory_reader()
        if available and available < self.minimum_free_bytes:
            return False, "insufficient_available_memory"
        return True, None

    def mark_loaded(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False


class DisabledImageProvider:
    """Honest production default until an approved component is installed."""

    def status(self) -> dict[str, object]:
        return {"name": "ARCHI Image", "state": ImageProviderState.DISABLED.value, "implemented": False, "resident": False}

    def generate(self, request: ImageRequest) -> ImageResult:
        return ImageResult(False, "ARCHI Image", ImageProviderState.DISABLED.value, error="archi_image_component_not_installed")

    def unload(self) -> None:
        return None


class LocalImageProvider:
    """Runs an approved sidecar once per request using a small JSON contract.

    The sidecar and its models must live under ``AppPaths.model_dir/archi-image``.
    A process-per-request design makes complete RAM/VRAM reclamation verifiable.
    """

    def __init__(self, model_dir: Path, *, runtime_name: str = "archi-image-runtime.exe", minimum_free_bytes: int = 6 * 1024**3, timeout_seconds: int = 300) -> None:
        self.component_dir = model_dir.expanduser().resolve() / "archi-image"
        self.runtime_path = self.component_dir / runtime_name
        self.resources = ModelResourceManager(self.component_dir, minimum_free_bytes=minimum_free_bytes)
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.state = ImageProviderState.UNLOADED
        self.last_error: str | None = None

    def status(self) -> dict[str, object]:
        installed = self.runtime_path.is_file()
        state = self.state if installed else ImageProviderState.UNAVAILABLE
        return {"name": "ARCHI Image", "state": state.value, "implemented": installed, "resident": self.resources.loaded}

    def generate(self, request: ImageRequest) -> ImageResult:
        started = time.perf_counter()
        if not self.runtime_path.is_file():
            return ImageResult(False, "ARCHI Image", ImageProviderState.UNAVAILABLE.value, error="archi_image_runtime_not_installed")
        admitted, error = self.resources.admit()
        if not admitted:
            return ImageResult(False, "ARCHI Image", ImageProviderState.UNLOADED.value, error=error)
        output = request.output_path.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        payload = {
            "schema_version": 1, "prompt": request.prompt.strip(), "negative_prompt": request.negative_prompt.strip(),
            "locale": request.locale, "width": request.width, "height": request.height,
            "seed": request.seed, "output_path": str(output),
        }
        if not payload["prompt"]:
            return ImageResult(False, "ARCHI Image", self.state.value, error="image_prompt_required")
        self.state = ImageProviderState.BUSY; self.resources.mark_loaded(); self.last_error = None
        try:
            completed = subprocess.run(
                [str(self.runtime_path), "--json-request"], input=json.dumps(payload), text=True,
                capture_output=True, timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                raise RuntimeError("image_runtime_failed")
            width, height = _image_dimensions(output)
            if width < 64 or height < 64:
                raise ValueError("image_output_dimensions_invalid")
            digest = _sha256(output)
            self.state = ImageProviderState.READY
            return ImageResult(True, "ARCHI Image", self.state.value, str(output), width, height, digest, round((time.perf_counter() - started) * 1000, 3))
        except subprocess.TimeoutExpired:
            self.last_error = "image_runtime_timeout"; self.state = ImageProviderState.ERROR
            output.unlink(missing_ok=True)
            return ImageResult(False, "ARCHI Image", self.state.value, elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=self.last_error)
        except Exception as exc:
            self.last_error = str(exc) or type(exc).__name__; self.state = ImageProviderState.ERROR
            output.unlink(missing_ok=True)
            return ImageResult(False, "ARCHI Image", self.state.value, elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=self.last_error)
        finally:
            self.unload()

    def unload(self) -> None:
        self.resources.unload()
        if self.state not in {ImageProviderState.ERROR, ImageProviderState.UNAVAILABLE}:
            self.state = ImageProviderState.UNLOADED


class StableDiffusionCppImageProvider:
    """Process-per-request SDXS provider with automatic CPU/Vulkan selection."""

    def __init__(
        self, model_path: Path, *, cpu_runtime: Path | None = None,
        vulkan_runtime: Path | None = None, backend: str = "auto",
        expected_sha256: str | None = None, timeout_seconds: int = 180,
    ) -> None:
        self.model_path = model_path.expanduser().resolve()
        self.cpu_runtime = cpu_runtime.expanduser().resolve() if cpu_runtime else None
        self.vulkan_runtime = vulkan_runtime.expanduser().resolve() if vulkan_runtime else None
        self.backend = backend
        self.expected_sha256 = expected_sha256.casefold() if expected_sha256 else None
        self.timeout_seconds = max(20, int(timeout_seconds))
        self.resources = ModelResourceManager(self.model_path.parent, minimum_free_bytes=2 * 1024**3)
        self.state = ImageProviderState.UNLOADED
        self.last_error: str | None = None
        self._verified_model_signature: tuple[int, int] | None = None
        self._verified_model_ok = False

    def _model_hash_valid(self) -> bool:
        if not self.expected_sha256:
            return True
        stat = self.model_path.stat()
        signature = (int(stat.st_size), int(stat.st_mtime_ns))
        if signature != self._verified_model_signature:
            self._verified_model_ok = _sha256(self.model_path) == self.expected_sha256
            self._verified_model_signature = signature
        return self._verified_model_ok

    def _runtime(self) -> tuple[Path | None, str]:
        if self.backend in {"auto", "vulkan"} and self.vulkan_runtime and self.vulkan_runtime.is_file():
            return self.vulkan_runtime, "vulkan"
        if self.backend in {"auto", "cpu"} and self.cpu_runtime and self.cpu_runtime.is_file():
            return self.cpu_runtime, "cpu"
        return None, self.backend

    def status(self) -> dict[str, object]:
        runtime, backend = self._runtime()
        installed = bool(runtime and self.model_path.is_file())
        return {
            "name": "ARCHI Image Lite", "state": (self.state if installed else ImageProviderState.UNAVAILABLE).value,
            "implemented": installed, "resident": self.resources.loaded, "backend": backend,
        }

    def generate(self, request: ImageRequest) -> ImageResult:
        started = time.perf_counter(); runtime, backend = self._runtime()
        if runtime is None or not self.model_path.is_file():
            return ImageResult(False, "ARCHI Image Lite", ImageProviderState.UNAVAILABLE.value, error="archi_image_component_not_installed")
        if not self._model_hash_valid():
            return ImageResult(False, "ARCHI Image Lite", ImageProviderState.ERROR.value, error="archi_image_model_hash_mismatch")
        admitted, error = self.resources.admit()
        if not admitted:
            return ImageResult(False, "ARCHI Image Lite", self.state.value, error=error)
        output = request.output_path.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        if not request.prompt.strip():
            return ImageResult(False, "ARCHI Image Lite", self.state.value, error="image_prompt_required")
        command = [
            str(runtime), "-m", str(self.model_path), "-p", request.prompt.strip(),
            "-n", request.negative_prompt.strip() or "words, letters, watermark, signature, distorted, blurry",
            "--steps", "1", "--cfg-scale", "1", "--sampling-method", "euler",
            "--scheduler", "discrete", "-W", str(max(256, min(768, request.width))),
            "-H", str(max(256, min(768, request.height))), "-s", str(request.seed if request.seed is not None else -1),
            "--backend", "vulkan0" if backend == "vulkan" else "cpu", "-o", str(output),
        ]
        if backend == "cpu":
            command += ["--threads", str(max(1, min(6, (os.cpu_count() or 6) - 1)))]
        self.state = ImageProviderState.BUSY; self.resources.mark_loaded(); self.last_error = None
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log = f"{completed.stdout}\n{completed.stderr}"
            if completed.returncode != 0 or "[ERROR]" in log or not output.is_file():
                raise RuntimeError("image_runtime_failed")
            width, height = _image_dimensions(output)
            if (width, height) != (max(256, min(768, request.width)), max(256, min(768, request.height))):
                raise ValueError("image_output_dimensions_invalid")
            self.state = ImageProviderState.READY
            return ImageResult(
                True, "ARCHI Image Lite", self.state.value, str(output), width, height,
                _sha256(output), round((time.perf_counter() - started) * 1000, 3),
            )
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.last_error = "image_runtime_timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
            self.state = ImageProviderState.ERROR; output.unlink(missing_ok=True)
            return ImageResult(False, "ARCHI Image Lite", self.state.value, elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=self.last_error)
        finally:
            self.unload()

    def unload(self) -> None:
        self.resources.unload()
        if self.state is not ImageProviderState.ERROR:
            self.state = ImageProviderState.UNLOADED


class NcnnVulkanUpscaleProvider:
    """Optional official Real-ESRGAN ncnn sidecar; no resident worker or FFmpeg."""

    def __init__(self, runtime: Path, models_dir: Path, *, timeout_seconds: int = 90) -> None:
        self.runtime = runtime.expanduser().resolve(); self.models_dir = models_dir.expanduser().resolve()
        self.timeout_seconds = max(10, int(timeout_seconds)); self.state = ImageProviderState.UNLOADED

    def status(self) -> dict[str, object]:
        installed = self.runtime.is_file() and (self.models_dir / "realesr-animevideov3-x2.param").is_file()
        return {"name": "ARCHI Image 2×", "state": (self.state if installed else ImageProviderState.UNAVAILABLE).value, "implemented": installed, "resident": False, "backend": "vulkan"}

    def upscale(self, source: Path, output: Path, *, scale: int = 2) -> ImageResult:
        started = time.perf_counter(); source = source.expanduser().resolve(); output = output.expanduser().resolve()
        if not self.status()["implemented"]:
            return ImageResult(False, "ARCHI Image 2×", ImageProviderState.UNAVAILABLE.value, error="image_upscaler_not_installed")
        if scale not in {2, 3, 4} or not source.is_file():
            return ImageResult(False, "ARCHI Image 2×", ImageProviderState.ERROR.value, error="invalid_upscale_request")
        source_width, source_height = _image_dimensions(source); output.parent.mkdir(parents=True, exist_ok=True); output.unlink(missing_ok=True)
        self.state = ImageProviderState.BUSY
        try:
            completed = subprocess.run([
                str(self.runtime), "-i", str(source), "-o", str(output), "-s", str(scale),
                "-t", "128", "-m", str(self.models_dir), "-n", "realesr-animevideov3",
                "-g", "0", "-j", "1:2:1", "-f", "png",
            ], capture_output=True, text=True, timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode != 0 or not output.is_file():
                raise RuntimeError("image_upscale_runtime_failed")
            width, height = _image_dimensions(output)
            if (width, height) != (source_width * scale, source_height * scale):
                raise ValueError("image_upscale_dimensions_invalid")
            self.state = ImageProviderState.UNLOADED
            return ImageResult(True, "ARCHI Image 2×", self.state.value, str(output), width, height, _sha256(output), round((time.perf_counter() - started) * 1000, 3))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            output.unlink(missing_ok=True); self.state = ImageProviderState.ERROR
            return ImageResult(False, "ARCHI Image 2×", self.state.value, elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error="image_upscale_runtime_timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc))


class RemoteImageProvider:
    """Opt-in adapter; transport and credential handling are injected by the host."""

    def __init__(self, transport: Callable[[ImageRequest], ImageResult] | None = None) -> None:
        self._transport = transport

    def status(self) -> dict[str, object]:
        return {"name": "ARCHI Image Remote", "state": (ImageProviderState.UNLOADED if self._transport else ImageProviderState.DISABLED).value, "implemented": self._transport is not None, "resident": False}

    def generate(self, request: ImageRequest) -> ImageResult:
        if self._transport is None:
            return ImageResult(False, "ARCHI Image Remote", ImageProviderState.DISABLED.value, error="remote_image_provider_not_configured")
        return self._transport(request)

    def unload(self) -> None:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int, int]:
    """Validate PNG/JPEG output with the standard library only."""
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1; continue
            marker = data[index + 1]; index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data): break
            length = int.from_bytes(data[index:index + 2], "big")
            if marker in range(0xC0, 0xC4) and index + 7 < len(data):
                return int.from_bytes(data[index + 5:index + 7], "big"), int.from_bytes(data[index + 3:index + 5], "big")
            index += length
    raise ValueError("image_output_invalid_or_unsupported")
