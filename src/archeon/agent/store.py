"""Atomic, local-only persistence for explicit AgentTask objectives."""

from __future__ import annotations

import json
import copy
import time
from pathlib import Path
from threading import RLock
from typing import Any

from .task import AgentMode, AgentStep, AgentTask, TaskContext, TaskStatus


class TaskStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self._lock = RLock()

    def save(self, task: AgentTask) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{task.id}.json"
        temporary = target.with_suffix(".json.tmp")
        payload = self._safe_payload(task.public())
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        return target

    @classmethod
    def _safe_payload(cls, value: Any) -> Any:
        """Keep task evidence while excluding document, screen and terminal bodies."""
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, item in value.items():
                if key in {
                    "content", "text", "stdout", "stderr", "diff", "command", "clipboard_text",
                    "stdout_tail", "stderr_tail", "window_summary", "visible_text", "controls",
                    "regions", "possible_actions",
                } or key.endswith("_body"):
                    output[key] = "<not persisted>"
                elif key in {"elements", "errors"} and isinstance(item, list):
                    output[key] = []
                    output[f"{key}_redacted"] = len(item)
                else:
                    output[key] = cls._safe_payload(item)
            return output
        if isinstance(value, list):
            return [cls._safe_payload(item) for item in value]
        if isinstance(value, tuple):
            return [cls._safe_payload(item) for item in value]
        return copy.deepcopy(value)

    def load(self, task_id: str) -> AgentTask | None:
        if not task_id or any(char not in "0123456789abcdef" for char in task_id.lower()):
            raise ValueError("invalid_task_id")
        target = (self.directory / f"{task_id}.json").resolve()
        if target.parent != self.directory:
            raise ValueError("invalid_task_id")
        if not target.exists():
            return None
        with self._lock:
            value: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        return AgentTask(
            id=str(value["id"]),
            goal=str(value["goal"]),
            plan=tuple(AgentStep(**step) for step in value.get("plan", [])),
            completion_criteria=tuple(str(item) for item in value.get("completion_criteria", [])),
            mode=AgentMode(value.get("mode", AgentMode.OBSERVE.value)),
            current_step=int(value.get("current_step", 0)),
            observations=list(value.get("observations", [])),
            actions=list(value.get("actions", [])),
            tool_results=list(value.get("tool_results", [])),
            errors=[str(item) for item in value.get("errors", [])],
            retries={str(key): int(item) for key, item in value.get("retries", {}).items()},
            replans=int(value.get("replans", 0)),
            cancellation=bool(value.get("cancellation", False)),
            status=TaskStatus(value.get("status", TaskStatus.PLANNING.value)),
            context=TaskContext(**value.get("context", {})),
            created_at=float(value.get("created_at", 0)),
            updated_at=float(value.get("updated_at", 0)),
        )

    def history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for path in self.directory.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                summaries.append({
                    "id": str(value["id"]), "goal": str(value.get("goal", ""))[:500],
                    "status": str(value.get("status", "planning")),
                    "current_step": int(value.get("current_step", 0)),
                    "step_count": len(value.get("plan", [])),
                    "updated_at": float(value.get("updated_at", 0)),
                    "recoverable": str(value.get("status", "planning")) not in {"completed", "cancelled"},
                })
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        summaries.sort(key=lambda item: item["updated_at"], reverse=True)
        return summaries[:max(1, min(int(limit), 500))]

    def recover(self, task_id: str) -> AgentTask:
        task = self.load(task_id)
        if task is None:
            raise FileNotFoundError("agent_task_not_found")
        if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise ValueError("agent_task_not_recoverable")
        task.cancellation = False
        task.status = TaskStatus.PLANNING
        task.updated_at = time.time()
        self.save(task)
        return task
