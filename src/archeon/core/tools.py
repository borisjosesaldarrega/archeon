"""Lazy tool registry, permission checks and verified result events."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .events import EventBus
from .lifecycle import ManagedComponent
from .permissions import Confirmer, PermissionEngine, RiskLevel


@dataclass(frozen=True, slots=True)
class ToolManifest:
    id: str
    description: str
    permissions: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.READ_ONLY
    timeout_seconds: float = 30.0
    resource_class: str = "light"


@dataclass(frozen=True, slots=True)
class ToolContext:
    correlation_id: str
    confirmer: Confirmer | None = None


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    verified: bool = False
    duration_ms: float = 0.0


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
            result = ToolResult(
                False,
                error=f"{type(error).__name__}: {error}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            event_type = "tool.failed"
        self._event_bus.publish(
            event_type,
            {"tool_id": tool_id, "ok": result.ok, "verified": result.verified},
            source="tool_engine",
            correlation_id=context.correlation_id,
        )
        return result

    @property
    def loaded_tool_count(self) -> int:
        return len(self._instances)

    def _start(self) -> None:
        self._event_bus.publish("tools.ready", {"count": len(self._factories)}, source="tool_engine")

    def _stop(self) -> None:
        for tool_id in tuple(self._instances):
            instance = self._instances.pop(tool_id)
            if callable(close := getattr(instance, "close", None)):
                close()
        self._permissions.clear_session()

