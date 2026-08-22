"""Minimal deterministic orchestrator; complex model routing stays unloaded."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .events import EventBus
from .language import LanguageContextEngine
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
    def __init__(
        self,
        event_bus: EventBus,
        tools: ToolEngine,
        language: LanguageContextEngine | None = None,
        *,
        conversation_language_provider: Callable[[], str] = lambda: "auto",
        interface_language_provider: Callable[[], str] = lambda: "es",
    ) -> None:
        self._event_bus = event_bus
        self._tools = tools
        self._language = language or LanguageContextEngine()
        self._conversation_language_provider = conversation_language_provider
        self._interface_language_provider = interface_language_provider
        self._last_language: str | None = None

    def handle_text(self, text: str) -> OrchestratorResponse:
        correlation_id = uuid.uuid4().hex
        normalized = _normalize(text)
        language = self._language.decide(
            text,
            preferred=self._conversation_language_provider(),
            previous=self._last_language,
            fallback=self._interface_language_provider(),
        )
        self._last_language = language.response_language
        self._event_bus.publish(
            "assistant.thinking",
            {"input_kind": "text", "response_language": language.response_language},
            source="orchestrator",
            correlation_id=correlation_id,
        )
        if normalized in {"estado", "estado del sistema", "system status", "please show the system status", "estado de la pc"}:
            result = self._tools.execute(
                "system.status",
                context=ToolContext(correlation_id=correlation_id),
            )
            response = self._from_tool(result, correlation_id, language.response_language)
        else:
            response = OrchestratorResponse(
                False,
                self._message("unsupported", language.response_language),
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
    def _from_tool(result: ToolResult, correlation_id: str, language: str = "es") -> OrchestratorResponse:
        if result.ok and result.verified:
            return OrchestratorResponse(True, Orchestrator._message("status", language), result.data, correlation_id)
        return OrchestratorResponse(False, result.error or Orchestrator._message("unverified", language), {}, correlation_id)

    @staticmethod
    def _message(key: str, language: str) -> str:
        messages = {
            "es": {"status": "Estado del sistema obtenido.", "unsupported": "Todavía no tengo una herramienta segura para esa orden.", "unverified": "La herramienta no pudo verificarse."},
            "en": {"status": "System status retrieved.", "unsupported": "I do not have a safe tool for that request yet.", "unverified": "The tool result could not be verified."},
            "pt": {"status": "Estado do sistema obtido.", "unsupported": "Ainda não tenho uma ferramenta segura para esse pedido.", "unverified": "Não foi possível verificar a ferramenta."},
            "fr": {"status": "État du système obtenu.", "unsupported": "Je ne dispose pas encore d’un outil sûr pour cette demande.", "unverified": "Le résultat de l’outil n’a pas pu être vérifié."},
            "de": {"status": "Systemstatus abgerufen.", "unsupported": "Für diese Anfrage habe ich noch kein sicheres Werkzeug.", "unverified": "Das Werkzeugergebnis konnte nicht verifiziert werden."},
            "it": {"status": "Stato del sistema ottenuto.", "unsupported": "Non ho ancora uno strumento sicuro per questa richiesta.", "unverified": "Non è stato possibile verificare il risultato."},
        }
        return messages.get(language, messages["en"]).get(key, messages["en"][key])
