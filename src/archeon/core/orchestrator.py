"""Minimal deterministic orchestrator; complex model routing stays unloaded."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from .events import EventBus
from .tools import ToolContext, ToolEngine, ToolResult


@dataclass(frozen=True, slots=True)
class OrchestratorResponse:
    ok: bool
    message: str
    data: Mapping[str, Any]
    correlation_id: str


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class Orchestrator:
    def __init__(self, event_bus: EventBus, tools: ToolEngine) -> None:
        self._event_bus = event_bus
        self._tools = tools

    def handle_text(self, text: str) -> OrchestratorResponse:
        correlation_id = uuid.uuid4().hex
        normalized = _normalize(text)
        self._event_bus.publish(
            "assistant.thinking",
            {"input_kind": "text"},
            source="orchestrator",
            correlation_id=correlation_id,
        )
        if normalized in {"estado", "estado del sistema", "system status", "estado de la pc"}:
            result = self._tools.execute(
                "system.status",
                context=ToolContext(correlation_id=correlation_id),
            )
            response = self._from_tool(result, correlation_id)
        else:
            response = OrchestratorResponse(
                False,
                "Todavía no tengo una herramienta segura para esa orden.",
                {},
                correlation_id,
            )
        self._event_bus.publish(
            "assistant.idle",
            {"ok": response.ok},
            source="orchestrator",
            correlation_id=correlation_id,
        )
        return response

    @staticmethod
    def _from_tool(result: ToolResult, correlation_id: str) -> OrchestratorResponse:
        if result.ok and result.verified:
            return OrchestratorResponse(True, "Estado del sistema obtenido.", result.data, correlation_id)
        return OrchestratorResponse(False, result.error or "La herramienta no pudo verificarse.", {}, correlation_id)

