"""Lazy tool registry, permission checks and verified result events."""

from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol
from threading import Event

from .events import EventBus
from .lifecycle import ManagedComponent
from .permissions import Confirmer, PermissionEngine, RiskLevel

logger = logging.getLogger("archeon.tools")


@dataclass(frozen=True, slots=True)
class ToolManifest:
    id: str
    description: str
    permissions: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.READ_ONLY
    timeout_seconds: float = 30.0
    resource_class: str = "light"
    supports_rollback: bool = False
    checkpoint_policy: str = "none"


@dataclass(frozen=True, slots=True)
class ToolContext:
    correlation_id: str
    confirmer: Confirmer | None = None
    scope_permissions: frozenset[str] = frozenset()
    cancel_event: Event | None = None


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    verified: bool = False
    duration_ms: float = 0.0
    error_code: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    changed_state: bool = False


class Tool(Protocol):
    manifest: ToolManifest

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult: ...

    def verify(self, context: ToolContext, result: ToolResult) -> bool: ...


ToolFactory = Callable[[], Tool]


class ToolEngine(ManagedComponent):
    def __init__(self, event_bus: EventBus, permissions: PermissionEngine) -> None:
        super().__init__("tools")
        self._event_bus = event_bus
        self._permissions = permissions
        self._factories: dict[str, tuple[ToolManifest, ToolFactory]] = {}
        self._instances: dict[str, Tool] = {}

    def register(self, manifest: ToolManifest, factory: ToolFactory) -> None:
        if manifest.id in self._factories:
            raise ValueError(f"tool already registered: {manifest.id}")
        self._factories[manifest.id] = (manifest, factory)

    def unregister(self, tool_id: str) -> None:
        instance = self._instances.pop(tool_id, None)
        if instance is not None and callable(close := getattr(instance, "close", None)):
            close()
        self._factories.pop(tool_id, None)

    def manifests(self) -> tuple[ToolManifest, ...]:
        return tuple(item[0] for item in self._factories.values())

    def execute(
        self,
        tool_id: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> ToolResult:
        if tool_id not in self._factories:
            return ToolResult(False, error=f"unknown tool: {tool_id}")
        manifest, factory = self._factories[tool_id]
        context = context or ToolContext(correlation_id=uuid.uuid4().hex)
        decision = self._permissions.evaluate(
            manifest.permissions,
            risk=manifest.risk,
            action=manifest.id,
            reason=manifest.description,
            confirmer=context.confirmer,
            ephemeral_grants=context.scope_permissions,
        )
        if not decision.allowed:
            self._event_bus.publish(
                "tool.denied",
                {"tool_id": tool_id, "reason": decision.reason},
                source="tool_engine",
                correlation_id=context.correlation_id,
            )
            return ToolResult(False, error=decision.reason)

        tool = self._instances.get(tool_id)
        if tool is None:
            tool = factory()
            if tool.manifest.id != manifest.id:
                raise RuntimeError("tool factory returned a mismatched manifest")
            self._instances[tool_id] = tool

        started = time.perf_counter()
        self._event_bus.publish(
            "tool.started",
            {"tool_id": tool_id},
            source="tool_engine",
            correlation_id=context.correlation_id,
        )
        try:
            result = tool.execute(context, dict(arguments or {}))
            result.duration_ms = (time.perf_counter() - started) * 1000
            result.verified = bool(result.ok and tool.verify(context, result))
            event_type = "tool.completed" if result.ok and result.verified else "tool.failed"
        except Exception as error:
            safe_arguments = dict(arguments or {})
            target = next((safe_arguments.get(key) for key in ("path", "output", "destination", "source") if safe_arguments.get(key)), None)
            logger.exception("Tool failed component=%s operation=execute target=%r", tool_id, target)
            result = ToolResult(
                False,
                data={"component": tool_id, "operation": "execute", "target": str(target) if target else None},
                error=f"{type(error).__name__}: {error}",
                duration_ms=(time.perf_counter() - started) * 1000,
                error_code="tool_exception",
            )
            event_type = "tool.failed"
        self._event_bus.publish(
            event_type,
            {
                "tool_id": tool_id, "ok": result.ok, "verified": result.verified,
                "error_code": result.error_code, "changed_state": result.changed_state,
            },
            source="tool_engine",
            correlation_id=context.correlation_id,
        )
        return result

    @property
    def loaded_tool_count(self) -> int:
        return len(self._instances)

    def release_active_inputs(self) -> dict[str, int]:
        """Emergency release for loaded input tools without loading new ones."""
        released = 0
        failed = 0
        for instance in tuple(self._instances.values()):
            callback = getattr(instance, "release_all", None)
            if not callable(callback):
                controller = getattr(instance, "_controller", None)
                callback = getattr(controller, "release_all_keys", None)
            if not callable(callback):
                mouse = getattr(instance, "_mouse", None)
                callback = getattr(mouse, "release_all", None)
            if not callable(callback):
                continue
            try:
                callback()
                released += 1
            except Exception:
                failed += 1
        return {"released": released, "failed": failed}

    def _start(self) -> None:
        self._event_bus.publish("tools.ready", {"count": len(self._factories)}, source="tool_engine")

    def _stop(self) -> None:
        for tool_id in tuple(self._instances):
            instance = self._instances.pop(tool_id)
            if callable(close := getattr(instance, "close", None)):
                close()
        self._permissions.clear_session()
