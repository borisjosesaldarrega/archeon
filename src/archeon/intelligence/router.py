"""Cheap deterministic routing before any model is loaded."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from archeon.core.language import normalize_text


class RouteDecision(StrEnum):
    TOOL = "tool"
    LOCAL_AI = "local_ai"


@dataclass(frozen=True, slots=True)
class ModelRoute:
    decision: RouteDecision
    reason: str


class ModelRouter:
    _SYSTEM_STATUS = {
        "estado", "estado del sistema", "system status",
        "please show the system status", "estado de la pc",
        "estado do sistema", "état du système", "etat du systeme",
        "systemstatus", "stato del sistema", "系统状态", "システム状態",
        "시스템 상태", "состояние системы", "حالة النظام", "सिस्टम की स्थिति",
    }

    @staticmethod
    def normalize(text: str) -> str:
        return normalize_text(text.strip())

    def route(self, text: str) -> ModelRoute:
        normalized = self.normalize(text)
        if normalized in self._SYSTEM_STATUS:
            return ModelRoute(RouteDecision.TOOL, "deterministic_system_intent")
        return ModelRoute(RouteDecision.LOCAL_AI, "requires_language_reasoning")
