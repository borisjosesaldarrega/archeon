"""Shared artifact contracts independent from UI and individual file libraries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ARTIFACT_FORMATS = frozenset({
    "docx", "xlsx", "pptx", "pdf", "png", "txt", "md", "csv", "json",
    "html", "css", "js", "py",
})


@dataclass(slots=True)
class ArtifactSpec:
    path: Path
    format: str
    title: str = ""
    content: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    sheets: list[dict[str, Any]] = field(default_factory=list)
    slides: list[dict[str, Any]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ArtifactSpec":
        path = Path(str(value.get("path", ""))).expanduser().resolve()
        artifact_format = str(value.get("format") or path.suffix.lstrip(".")).casefold().strip()
        if artifact_format not in ARTIFACT_FORMATS:
            raise ValueError("unsupported_artifact_format")
        if path.suffix.casefold() != f".{artifact_format}":
            raise ValueError("artifact_extension_mismatch")
        return cls(
            path=path, format=artifact_format, title=str(value.get("title", "")),
            content=str(value.get("content", "")),
            sections=[dict(item) for item in value.get("sections", [])],
            sheets=[dict(item) for item in value.get("sheets", [])],
            slides=[dict(item) for item in value.get("slides", [])],
            rows=[list(item) for item in value.get("rows", [])],
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    path: str
    format: str
    bytes: int
    sha256: str
    verified: bool
    structure: dict[str, Any]
    checkpoint: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "path": self.path, "format": self.format, "bytes": self.bytes,
            "sha256": self.sha256, "verified": self.verified,
            "structure": self.structure, "checkpoint": self.checkpoint,
        }
