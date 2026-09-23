"""Atomic, hash-pinned management for the optional ARCHI Vision component."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Callable


class VisionState(StrEnum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    BUSY = "busy"
    UNLOADING = "unloading"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class VisionArtifact:
    role: str
    filename: str
    source: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VisionComponentDescriptor:
    internal_id: str
    public_name: str
    version: str
    license: str
    source_revision: str
    artifacts: tuple[VisionArtifact, ...]

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.artifacts)


_REPOSITORY = "https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF"
ARCHI_VISION_REFERENCE = VisionComponentDescriptor(
    internal_id="archi-vision-reference-1",
    public_name="ARCHI Vision",
    version="Qwen3-VL-2B-Instruct@52d6c8ffea26cc873ac5ad116f8631268d7eb503",
    license="Apache-2.0",
    source_revision="52d6c8ffea26cc873ac5ad116f8631268d7eb503",
    artifacts=(
        VisionArtifact(
            "language_model", "archi-vision-reference-q4.gguf",
            f"{_REPOSITORY}/resolve/52d6c8ffea26cc873ac5ad116f8631268d7eb503/Qwen3VL-2B-Instruct-Q4_K_M.gguf",
            1_107_409_952, "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae",
        ),
        VisionArtifact(
            "projector", "archi-vision-reference-projector-q8.gguf",
            f"{_REPOSITORY}/resolve/52d6c8ffea26cc873ac5ad116f8631268d7eb503/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf",
            445_053_216, "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82",
        ),
    ),
)


class VisionComponentManager:
    """Install optional artifacts under AppPaths.model_dir, never the repository."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir.expanduser().resolve()
        self.component_dir = self.model_dir / "archi-vision"
        self.manifest_path = self.component_dir / "manifest.json"
        self.state = VisionState.UNLOADED
        self.last_error: str | None = None

    def installed(self, descriptor: VisionComponentDescriptor = ARCHI_VISION_REFERENCE) -> bool:
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if manifest.get("internal_id") != descriptor.internal_id:
            return False
        return all(self._artifact_valid(item) for item in descriptor.artifacts)

    def install_test_component(
        self,
        descriptor: VisionComponentDescriptor = ARCHI_VISION_REFERENCE,
        *,
        opener: Callable[[str], BinaryIO] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, object]:
        self.state = VisionState.LOADING
        self.last_error = None
        self.component_dir.mkdir(parents=True, exist_ok=True)
        required = descriptor.total_size_bytes + 512 * 1024 * 1024
        if shutil.disk_usage(self.component_dir).free < required:
            self.state = VisionState.ERROR
            self.last_error = "insufficient_disk_space"
            raise OSError(self.last_error)
        open_stream = opener or (lambda url: urllib.request.urlopen(url, timeout=60))
        try:
            for artifact in descriptor.artifacts:
                if self._artifact_valid(artifact):
                    if progress:
                        progress(artifact.role, artifact.size_bytes, artifact.size_bytes)
                    continue
                target = self.component_dir / artifact.filename
                temporary = target.with_suffix(target.suffix + ".part")
                digest = hashlib.sha256()
                written = 0
                with open_stream(artifact.source) as source, temporary.open("wb") as destination:
                    while True:
                        chunk = source.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > artifact.size_bytes:
                            raise ValueError("vision_artifact_size_mismatch")
                        digest.update(chunk)
                        destination.write(chunk)
                        if progress:
                            progress(artifact.role, written, artifact.size_bytes)
                    destination.flush()
                    os.fsync(destination.fileno())
                if written != artifact.size_bytes:
                    raise ValueError("vision_artifact_size_mismatch")
                if digest.hexdigest().lower() != artifact.sha256:
                    raise ValueError("vision_artifact_sha256_mismatch")
                os.replace(temporary, target)
            payload = {
                "schema_version": 1, "internal_id": descriptor.internal_id,
                "public_name": descriptor.public_name, "version": descriptor.version,
                "license": descriptor.license, "source_revision": descriptor.source_revision,
                "artifacts": [asdict(item) for item in descriptor.artifacts],
            }
            temporary_manifest = self.manifest_path.with_suffix(".json.tmp")
            temporary_manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary_manifest, self.manifest_path)
            self.state = VisionState.UNLOADED
            return self.status(developer=True)
        except Exception as error:
            self.state = VisionState.ERROR
            self.last_error = type(error).__name__
            for part in self.component_dir.glob("*.part"):
                part.unlink(missing_ok=True)
            raise

    def artifact_path(self, role: str) -> Path:
        artifact = next((item for item in ARCHI_VISION_REFERENCE.artifacts if item.role == role), None)
        if artifact is None:
            raise KeyError(role)
        return self.component_dir / artifact.filename

    def status(self, *, developer: bool = False) -> dict[str, object]:
        installed = self.installed()
        public: dict[str, object] = {
            "name": "ARCHI Vision", "state": self.state.value,
            "installed": installed,
            "download_size_bytes": ARCHI_VISION_REFERENCE.total_size_bytes,
            "disk_required_bytes": ARCHI_VISION_REFERENCE.total_size_bytes + 512 * 1024 * 1024,
            "last_error": self.last_error,
        }
        if developer:
            public.update({
                "internal_id": ARCHI_VISION_REFERENCE.internal_id,
                "version": ARCHI_VISION_REFERENCE.version,
                "license": ARCHI_VISION_REFERENCE.license,
                "model_dir": str(self.component_dir),
            })
        return public

    def _artifact_valid(self, artifact: VisionArtifact) -> bool:
        path = self.component_dir / artifact.filename
        if not path.is_file() or path.stat().st_size != artifact.size_bytes:
            return False
        receipt = path.with_suffix(path.suffix + ".sha256")
        try:
            if receipt.read_text(encoding="ascii").strip() == artifact.sha256:
                return True
        except OSError:
            pass
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        valid = digest.hexdigest().lower() == artifact.sha256
        if valid:
            receipt.write_text(artifact.sha256 + "\n", encoding="ascii")
        return valid
