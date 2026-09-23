"""Permission-gated plan/act/observe/verify continuation loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, RLock
from typing import Any, Callable, Mapping

from archeon.core.events import EventBus
from archeon.core.permissions import Confirmer
from archeon.core.tools import ToolContext, ToolEngine, ToolResult

from .task import AgentStep, AgentTask, TaskStatus


StepVerifier = Callable[[AgentTask, AgentStep, ToolResult], bool]
TaskReplanner = Callable[[AgentTask, AgentStep, ToolResult], tuple[AgentStep, ...] | None]
TaskCheckpoint = Callable[[AgentTask], Any]
ResultObserver = Callable[[AgentTask, AgentStep, ToolResult], Any]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    allowed: bool
    reason: str


class ToolValidator:
    """Reject planner output that is not grounded in a registered tool."""

    def __init__(self, tools: ToolEngine) -> None:
        self._tools = tools

    def validate(self, step: AgentStep) -> ValidationResult:
        manifests = {item.id: item for item in self._tools.manifests()}
        if step.tool_id not in manifests:
            return ValidationResult(False, f"unknown tool: {step.tool_id}")
        if not isinstance(step.arguments, Mapping):
            return ValidationResult(False, "tool arguments must be a mapping")
        if step.max_retries < 0 or step.max_retries > 5:
            return ValidationResult(False, "invalid retry budget")
        return ValidationResult(True, "registered tool")


class AgentRunner:
    def __init__(
        self,
        events: EventBus,
        tools: ToolEngine,
        *,
        verifier: StepVerifier | None = None,
        replanner: TaskReplanner | None = None,
        max_actions: int = 32,
        max_task_seconds: float = 300.0,
        checkpoint: TaskCheckpoint | None = None,
        result_observer: ResultObserver | None = None,
    ) -> None:
        self._events = events
        self._tools = tools
        self._validator = ToolValidator(tools)
        self._verifier = verifier or (lambda _task, _step, result: result.ok and result.verified)
        self._replanner = replanner
        self._max_actions = max(1, min(128, max_actions))
        self._max_task_seconds = max(1.0, min(3600.0, max_task_seconds))
        self._checkpoint_callback = checkpoint
        self._result_observer = result_observer
        self._active: dict[str, AgentTask] = {}
        self._cancel_events: dict[str, Event] = {}
        self._active_lock = RLock()
        self._continue = Event()
        self._continue.set()

    def cancel_active(self) -> int:
        with self._active_lock:
            tasks = tuple(self._active.values())
        for task in tasks:
            task.cancellation = True
            task.updated_at = time.time()
            event = self._cancel_events.get(task.id)
            if event is not None:
                event.set()
        self._continue.set()
        return len(tasks)

    def pause_active(self) -> int:
        with self._active_lock:
            count = len(self._active)
        if count:
            self._continue.clear()
            self._events.publish("agent.task.paused", {"task_count": count}, source="agent_runner")
        return count

    def resume_active(self) -> int:
        with self._active_lock:
            count = len(self._active)
        self._continue.set()
        if count:
            self._events.publish("agent.task.resumed", {"task_count": count}, source="agent_runner")
        return count

    @property
    def active_task_count(self) -> int:
        with self._active_lock:
            return len(self._active)

    def run(
        self,
        task: AgentTask,
        *,
        confirmer: Confirmer | None = None,
        scope_permissions: frozenset[str] = frozenset(),
    ) -> AgentTask:
        if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            return task
        task.status = TaskStatus.ACTING
        with self._active_lock:
            self._active[task.id] = task
            cancel_event = Event()
            self._cancel_events[task.id] = cancel_event
        actions = 0
        run_started = time.monotonic()
        self._publish("agent.task.started", task, {"goal": task.goal})
        self._checkpoint(task)
        while task.active_step is not None and actions < self._max_actions:
            if task.cancellation:
                task.status = TaskStatus.CANCELLED
                break
            while not self._continue.wait(0.05):
                if task.cancellation:
                    task.status = TaskStatus.CANCELLED
                    break
            if task.cancellation:
                break
            if time.monotonic() - run_started >= self._max_task_seconds:
                task.errors.append("maximum task time reached")
                task.status = TaskStatus.FAILED
                break
            step = task.active_step
            validation = self._validator.validate(step)
            if not validation.allowed:
                task.errors.append(validation.reason)
                if step.continue_on_failure:
                    task.failed_subtasks.append({"step": step.id, "tool_id": step.tool_id, "error": validation.reason})
                    self._publish("agent.step.failed", task, {"step": step.id, "error": validation.reason})
                    task.current_step += 1
                    task.updated_at = time.time()
                    self._checkpoint(task)
                    continue
                task.status = TaskStatus.FAILED
                break
            actions += 1
            task.status = TaskStatus.OBSERVING if ".observe" in step.tool_id else TaskStatus.ACTING
            self._publish("agent.step.started", task, {"step": step.id, "tool_id": step.tool_id})
            try:
                resolved_arguments = self._resolve_arguments(task, step.arguments)
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                task.errors.append(f"{step.id}: argument resolution failed: {error}")
                if step.continue_on_failure:
                    task.failed_subtasks.append({"step": step.id, "tool_id": step.tool_id, "error": f"argument resolution failed: {error}"})
                    self._publish("agent.step.failed", task, {"step": step.id, "error": str(error)})
                    task.current_step += 1
                    task.updated_at = time.time()
                    self._checkpoint(task)
                    continue
                task.status = TaskStatus.FAILED
                break
            result = self._tools.execute(
                step.tool_id,
                resolved_arguments,
                context=ToolContext(
                    correlation_id=task.id,
                    confirmer=confirmer,
                    scope_permissions=scope_permissions,
                    cancel_event=cancel_event,
                ),
            )
            recorded = {
                "step": step.id,
                "tool_id": step.tool_id,
                "ok": result.ok,
                "verified": result.verified,
                "duration_ms": round(result.duration_ms, 3),
                "data": dict(result.data),
                "error": result.error,
                "error_code": result.error_code,
                "evidence": dict(result.evidence),
                "changed_state": result.changed_state,
            }
            task.tool_results.append(recorded)
            task.actions.append({"step": step.id, "tool_id": step.tool_id, "at": time.time()})
            task.observations.append({"step": step.id, "result": recorded, "at": time.time()})
            self._update_context(task, step, result)
            if self._result_observer is not None:
                try:
                    self._result_observer(task, step, result)
                except (OSError, RuntimeError, TypeError, ValueError):
                    self._events.publish("agent.visual.failed", {"step": step.id}, source="agent_runner", correlation_id=task.id)
            self._checkpoint(task)
            if result.error and result.error.startswith("confirmation required:"):
                task.status = TaskStatus.WAITING_PERMISSION
                self._publish("agent.task.waiting_permission", task, {"step": step.id})
                break
            if task.cancellation:
                task.status = TaskStatus.CANCELLED
                self._publish("agent.step.cancelled", task, {"step": step.id})
                break
            task.status = TaskStatus.VERIFYING
            if self._verifier(task, step, result):
                self._publish("agent.step.verified", task, {"step": step.id})
                task.current_step += 1
                task.updated_at = time.time()
                self._checkpoint(task)
                continue
            attempt = task.retries.get(step.id, 0)
            if result.error:
                task.errors.append(f"{step.id}: {result.error}")
            if attempt < step.max_retries:
                task.retries[step.id] = attempt + 1
                self._publish("agent.step.retry", task, {"step": step.id, "retry": attempt + 1})
                continue
            replacement = self._replanner(task, step, result) if self._replanner is not None else None
            if replacement:
                task.plan = task.plan[:task.current_step] + tuple(replacement)
                task.replans += 1
                task.updated_at = time.time()
                self._publish("agent.task.replanned", task, {"step": step.id, "replans": task.replans})
                continue
            self._publish("agent.step.failed", task, {"step": step.id, "error": result.error})
            if step.continue_on_failure:
                if not result.error:
                    task.errors.append(f"{step.id}: verification_failed")
                task.failed_subtasks.append({"step": step.id, "tool_id": step.tool_id, "error": result.error or "verification_failed"})
                task.current_step += 1
                task.updated_at = time.time()
                self._checkpoint(task)
                continue
            task.status = TaskStatus.FAILED
            break
        if task.active_step is None and not task.cancellation:
            task.status = TaskStatus.PARTIAL if task.failed_subtasks else TaskStatus.COMPLETED
        elif actions >= self._max_actions and task.status in {TaskStatus.ACTING, TaskStatus.VERIFYING}:
            task.errors.append("maximum action budget reached")
            task.status = TaskStatus.FAILED
        task.updated_at = time.time()
        self._checkpoint(task)
        self._publish(f"agent.task.{task.status.value}", task, {"actions": actions})
        with self._active_lock:
            self._active.pop(task.id, None)
            self._cancel_events.pop(task.id, None)
        return task

    def _checkpoint(self, task: AgentTask) -> None:
        if self._checkpoint_callback is None:
            return
        try:
            self._checkpoint_callback(task)
        except OSError as error:
            self._events.publish(
                "agent.task.checkpoint_failed", {"task_id": task.id, "error_type": type(error).__name__},
                source="agent_runner", correlation_id=task.id,
            )

    @classmethod
    def _resolve_arguments(cls, task: AgentTask, value: Any) -> Any:
        if isinstance(value, Mapping):
            if "$template" in value:
                template = str(value["$template"])
                variables = value.get("$vars", {})
                if not isinstance(variables, Mapping):
                    raise ValueError("template variables must be a mapping")
                resolved = {str(key): cls._resolve_arguments(task, item) for key, item in variables.items()}
                try:
                    return template.format_map(resolved)
                except (KeyError, ValueError) as error:
                    raise ValueError(f"invalid result template: {error}") from error
            if "$result" in value:
                step_id = str(value["$result"])
                match = next(
                    (item for item in reversed(task.tool_results) if item.get("step") == step_id), None,
                )
                if match is None:
                    raise ValueError(f"missing tool result: {step_id}")
                selected: Any = match.get("data", {})
                for part in str(value.get("path", "")).split("."):
                    if not part:
                        continue
                    if isinstance(selected, (list, tuple)) and part.isdigit():
                        index = int(part)
                        if index >= len(selected):
                            raise ValueError(f"missing result field: {step_id}.{value.get('path', '')}")
                        selected = selected[index]
                        continue
                    if not isinstance(selected, Mapping) or part not in selected:
                        raise ValueError(f"missing result field: {step_id}.{value.get('path', '')}")
                    selected = selected[part]
                return selected
            if "$context" in value:
                selected = task.context
                for part in str(value["$context"]).split("."):
                    selected = getattr(selected, part)
                return selected
            return {key: cls._resolve_arguments(task, item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._resolve_arguments(task, item) for item in value]
        return value

    def _publish(self, event: str, task: AgentTask, payload: Mapping[str, Any]) -> None:
        event_payload = dict(payload)
        active = task.active_step
        event_payload.update({
            "task_id": task.id,
            "goal": task.goal,
            "status": task.status.value,
            "current_step": task.current_step,
            "step_count": len(task.plan),
            "step_description": active.description if active else "",
        })
        self._events.publish(event, event_payload, source="agent_runner", correlation_id=task.id)

    @staticmethod
    def _update_context(task: AgentTask, step: AgentStep, result: ToolResult) -> None:
        """Keep multi-tool references grounded in verified tool output."""
        if not result.ok:
            return
        data = result.data
        window = data.get("window") or data.get("target_window")
        if isinstance(window, Mapping):
            task.context.remember_window(window)
        windows = data.get("windows")
        if isinstance(windows, list) and len(windows) == 1 and isinstance(windows[0], Mapping):
            task.context.remember_window(windows[0])
        path = data.get("path")
        if isinstance(path, str) and path:
            if step.tool_id.startswith("programming."):
                task.context.active_project = path
                task.context.active_folder = path
            elif step.tool_id.startswith("documents.") or step.tool_id == "files.read":
                task.context.selected_file = path
            elif step.tool_id.startswith("files."):
                task.context.active_folder = path
        if step.tool_id == "browser.download" and isinstance(path, str):
            task.context.recent_download = path
        url = data.get("url")
        if isinstance(url, str) and url:
            task.context.current_url = url
        tab_id = data.get("id") or data.get("tab_id")
        if step.tool_id.startswith("browser.") and tab_id is not None:
            task.context.current_tab = str(tab_id)
