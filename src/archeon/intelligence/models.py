"""Stable model contracts and an atomic local model registry."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Mapping


class ModelState(StrEnum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    UNLOADING = "unloading"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    id: str
    family: str
    filename: str
    quantization: str
    size_bytes: int
    sha256: str
    source: str
    license: str
    version: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelDescriptor":
        return cls(
            id=str(value["id"]), family=str(value["family"]), filename=str(value["filename"]),
            quantization=str(value["quantization"]), size_bytes=int(value["size_bytes"]),
            sha256=str(value["sha256"]).lower(), source=str(value["source"]),
            license=str(value["license"]), version=str(value["version"]),
        )


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[Mapping[str, str], ...]
    max_tokens: int = 512
    temperature: float = 0.3
    response_format: Mapping[str, Any] | None = None
    enable_thinking: bool = False
    on_token: Callable[[str], None] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    load_ms: float
    first_token_ms: float | None
    total_ms: float
    timings: Mapping[str, Any] = field(default_factory=dict)


class ModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir.resolve()
        self.path = self.models_dir / "registry.json"

    def all(self) -> tuple[ModelDescriptor, ...]:
        if not self.path.is_file():
            return ()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        records = value.get("models", []) if isinstance(value, dict) else []
        return tuple(ModelDescriptor.from_mapping(item) for item in records if isinstance(item, dict))

    def get(self, model_id: str) -> ModelDescriptor | None:
        return next((item for item in self.all() if item.id == model_id), None)

    def register(self, descriptor: ModelDescriptor) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        records = {item.id: item for item in self.all()}
        records[descriptor.id] = descriptor
        payload = json.dumps(
            {"schema_version": 1, "models": [asdict(item) for item in records.values()]},
            ensure_ascii=False, indent=2,
        )
        with NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=self.models_dir,
            prefix="registry-", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, self.path)

    def model_path(self, descriptor: ModelDescriptor) -> Path:
        candidate = (self.models_dir / descriptor.filename).resolve()
        if self.models_dir != candidate and self.models_dir not in candidate.parents:
            raise ValueError("invalid_model_filename")
        return candidate
