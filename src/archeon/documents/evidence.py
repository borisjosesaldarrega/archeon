"""Verified screenshot evidence contracts and privacy-aware manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceCapture:
    source: str
    timestamp: str
    task_step: str
    target: str
    image_path: str
    caption: str
    url: str = ""
    viewport: str = ""
    sha256: str = ""
    privacy_checked: bool = True

    @classmethod
    def from_file(
        cls, path: str | Path, *, source: str, task_step: str, target: str,
        caption: str, url: str = "", viewport: str = "",
        visible_text: str = "",
    ) -> "EvidenceCapture":
        image = Path(path).expanduser().resolve()
        if not image.is_file() or image.stat().st_size < 128:
            raise FileNotFoundError("evidence_image_missing")
        if re.search(r"(?:password|contrase[nñ]a|token|api[_ -]?key|authorization:)\s*\S+", visible_text, re.I):
            raise ValueError("evidence_may_contain_sensitive_data")
        return cls(
            source=source, timestamp=datetime.now(timezone.utc).isoformat(), task_step=task_step,
            target=target, image_path=str(image), caption=caption, url=url, viewport=viewport,
            sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        )

    def public(self) -> dict[str, Any]: return asdict(self)


def write_evidence_manifest(path: str | Path, captures: list[EvidenceCapture]) -> Path:
    target = Path(path).expanduser().resolve()
    for capture in captures:
        image = Path(capture.image_path)
        if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != capture.sha256:
            raise ValueError("evidence_digest_mismatch")
    target.write_text(json.dumps({"evidence": [item.public() for item in captures]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
