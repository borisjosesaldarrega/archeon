"""Serializable state for a bounded, cancellable ARCHEON agent objective."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class TaskStatus(StrEnum):
    PLANNING = "planning"
    PLANNED = "planning"
    OBSERVING = "observing"
    ACTING = "acting"
    RUNNING = "acting"
    VERIFYING = "verifying"
    WAITING_PERMISSION = "waiting_permission"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMode(StrEnum):
    OBSERVE = "observe"
    GUIDE = "guide"
    CONTROL = "control"


@dataclass(slots=True)
class TaskContext:
    active_app: str | None = None
    active_window: str | None = None
    previous_window: dict[str, Any] | None = None
    target_window: dict[str, Any] | None = None
    active_project: str | None = None
    active_folder: str | None = None
    selected_file: str | None = None
    recent_download: str | None = None
    current_url: str | None = None
    current_tab: str | None = None
    recent_entities: list[dict[str, Any]] = field(default_factory=list)
    document_history: list[dict[str, Any]] = field(default_factory=list)
    writing_feedback: dict[str, int] = field(default_factory=dict)
    current_page: int | None = None
    current_goal: str | None = None

    def remember_window(self, window: Mapping[str, Any] | None) -> None:
        """Advance window context without losing the last verified target."""
        if not window:
            return
        normalized = dict(window)
        handle = int(normalized.get("handle", 0) or 0)
        current_handle = int((self.target_window or {}).get("handle", 0) or 0)
        if handle and current_handle and handle != current_handle:
            self.previous_window = dict(self.target_window or {})
        self.target_window = normalized
        self.active_window = str(normalized.get("title") or "") or self.active_window
        self.active_app = str(normalized.get("process_name") or "") or self.active_app

    def remember_document(self, path: str, *, page: int | None = None, source: str = "resolved") -> None:
        """Keep bounded verified document references for follow-up phrases."""
        normalized = str(path)
        self.selected_file = normalized
        self.current_page = page
        entry = {"path": normalized, "page": page, "source": source, "remembered_at": time.time()}
        self.document_history = [item for item in self.document_history if item.get("path") != normalized]
        self.document_history.append(entry)
        self.document_history = self.document_history[-12:]

    def referenced_document(self, reference: str = "current") -> str | None:
        history = [str(item.get("path")) for item in self.document_history if item.get("path")]
        if reference == "previous" and len(history) >= 2:
            return history[-2]
        return self.selected_file or (history[-1] if history else None)

    def remember_writing_feedback(self, preference: str) -> None:
        """Learn only after repetition; counts remain local and contain no document text."""
        key = str(preference).casefold().strip()
        if key not in {"concise", "avoid_generic_conclusion", "less_formal"}:
            return
        self.writing_feedback[key] = min(20, int(self.writing_feedback.get(key, 0)) + 1)

    def learned_writing_preferences(self) -> dict[str, bool]:
        return {key: count >= 2 for key, count in self.writing_feedback.items()}


@dataclass(frozen=True, slots=True)
class AgentStep:
    id: str
    description: str
    tool_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    completion_criteria: str = "verified tool result"
    max_retries: int = 1
    expected_state: Mapping[str, Any] = field(default_factory=dict)
    continue_on_failure: bool = False


@dataclass(slots=True)
class AgentTask:
    goal: str
    plan: tuple[AgentStep, ...]
    completion_criteria: tuple[str, ...]
    mode: AgentMode = AgentMode.OBSERVE
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    current_step: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_subtasks: list[dict[str, Any]] = field(default_factory=list)
    retries: dict[str, int] = field(default_factory=dict)
    replans: int = 0
    cancellation: bool = False
    status: TaskStatus = TaskStatus.PLANNING
    context: TaskContext = field(default_factory=TaskContext)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def active_step(self) -> AgentStep | None:
        return self.plan[self.current_step] if self.current_step < len(self.plan) else None

    def cancel(self) -> None:
        self.cancellation = True
        self.status = TaskStatus.CANCELLED
        self.updated_at = time.time()

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value
