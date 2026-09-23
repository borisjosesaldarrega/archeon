"""Device-local persistence for bounded task references, never document bodies."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from .task import TaskContext


class TaskContextStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def load(self) -> TaskContext:
        if not self.path.is_file():
            return TaskContext()
        try:
            with self._lock:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = TaskContext.__dataclass_fields__.keys()
            return TaskContext(**{key: item for key, item in value.items() if key in allowed})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return TaskContext()

    def save(self, context: TaskContext) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = asdict(context)
        # Only references and UI state are persisted. Document contents and tool output are absent by design.
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
