"""Evidence-only improvement candidates; never self-modifies or auto-applies."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ImprovementCandidate:
    title: str
    problem: str
    evidence: tuple[dict[str, Any], ...]
    proposed_change: str
    validation_plan: tuple[str, ...]
    risk: str
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)
    approval_required: bool = True
    applied: bool = False


class ImprovementRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve(); self._lock = RLock()

    def record(self, candidate: ImprovementCandidate) -> Path:
        if candidate.applied or not candidate.approval_required:
            raise ValueError("uncontrolled_improvement_candidate_rejected")
        if not candidate.evidence or not candidate.validation_plan:
            raise ValueError("improvement_evidence_and_validation_required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            values = self.list(); values.append(asdict(candidate))
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return self.path

    def list(self) -> list[dict[str, Any]]:
        if not self.path.is_file(): return []
        with self._lock: return list(json.loads(self.path.read_text(encoding="utf-8")))
