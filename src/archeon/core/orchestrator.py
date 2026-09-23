"""Minimal deterministic orchestrator; complex model routing stays unloaded."""

from __future__ import annotations

import unicodedata
import uuid
import time
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .events import EventBus
from .language import LanguageContextEngine, normalize_text
from .messages import core_message, identity_message, product_help_message, response_directive
from .tools import ToolContext, ToolEngine, ToolResult
from archeon.intelligence import GenerationRequest, ModelManager, ModelRouter, RouteDecision
from archeon.context import ContextBudgetManager, ContextRelevanceGate, ConversationMemory, ResponseBudgetManager
from archeon.understanding.intent_guard import is_product_help_request


@dataclass(frozen=True, slots=True)
class OrchestratorResponse:
    ok: bool
    message: str
    data: Mapping[str, Any]
    correlation_id: str


def _normalize(text: str) -> str:
    return normalize_text(text.strip())


class Orchestrator:
    def __init__(
        self,
        event_bus: EventBus,
        tools: ToolEngine,
        language: LanguageContextEngine | None = None,
        *,
        conversation_language_provider: Callable[[], str] = lambda: "auto",
        interface_language_provider: Callable[[], str] = lambda: "es",
        model_manager: ModelManager | None = None,
        personality_provider: Callable[[], Mapping[str, Any]] = lambda: {},
        generation_provider: Callable[[], Mapping[str, Any]] = lambda: {},
        memory_enabled_provider: Callable[[], bool] = lambda: True,
        conversation_turns_provider: Callable[[], int] = lambda: 4,
    ) -> None:
        self._event_bus = event_bus
        self._tools = tools
        self._language = language or LanguageContextEngine()
        self._conversation_language_provider = conversation_language_provider
        self._interface_language_provider = interface_language_provider
        self._last_language: str | None = None
        self._models = model_manager
        self._router = ModelRouter()
        self._personality_provider = personality_provider
        self._generation_provider = generation_provider
        self._memory_enabled_provider = memory_enabled_provider
        self._conversation_turns_provider = conversation_turns_provider
        self._memory = ConversationMemory()
        self._context_budget = ContextBudgetManager()
        self._context_relevance = ContextRelevanceGate()
        self._response_budget = ResponseBudgetManager()

    def clear_memory(self) -> None:
        self._memory.clear()

    def _remember(self, text: str, response: OrchestratorResponse) -> None:
        if self._memory_enabled_provider() and response.ok and response.message:
            self._memory.add_turn(text, response.message)

    def handle_text(
        self,
        text: str,
        attachments: Sequence[Mapping[str, Any]] = (),
        *,
        response_token_floor: int = 0,
    ) -> OrchestratorResponse:
        input_started = time.perf_counter()
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
        identity = self._identity_response(normalized, correlation_id, language.response_language)
        if identity is not None:
            self._event_bus.publish(
                "assistant.idle", {"ok": True}, source="orchestrator", correlation_id=correlation_id,
            )
            self._remember(text, identity)
            return identity
        product_help = self._product_help_response(normalized, correlation_id, language.response_language)
        if product_help is not None:
            self._event_bus.publish(
                "assistant.idle", {"ok": True}, source="orchestrator", correlation_id=correlation_id,
            )
            self._remember(text, product_help)
            return product_help
        route = self._router.route(text)
        routing_complete_ms = (time.perf_counter() - input_started) * 1000
        if route.decision is RouteDecision.TOOL:
            result = self._tools.execute(
                "system.status",
                context=ToolContext(correlation_id=correlation_id),
            )
            response = self._from_tool(result, correlation_id, language.response_language)
        elif attachments:
            response = OrchestratorResponse(
                False, self._message("attachment_unavailable", language.response_language),
                {"route": "attachment_reader", "attachments": [dict(item) for item in attachments]},
                correlation_id,
            )
        elif self._models is not None and self._models.available:
            try:
                generation = self._generation_provider()
                personality = self._personality_provider()
                configured_tokens = max(
                    int(generation.get("max_tokens", 512)),
                    max(0, min(4096, int(response_token_floor))),
                )
                response_budget = self._response_budget.allocate(
                    text, configured_max=configured_tokens, detail=int(personality.get("detail", 50)),
                )
                token_budget = response_budget.max_tokens
                recent = self._memory.recent(self._conversation_turns_provider()) if self._memory_enabled_provider() else ()
                recent = self._context_relevance.filter(text, recent)
                context = self._context_budget.build(
                    system=self._system_prompt(language.response_language), user=text,
                    recent_conversation=recent,
                    max_prompt_tokens=max(512, int(generation.get("context_size", 4096)) - token_budget - 128),
                )
                context_complete_ms = (time.perf_counter() - input_started) * 1000
                first_stream_ms: float | None = None

                def stream_token(delta: str) -> None:
                    nonlocal first_stream_ms
                    delta = re.sub(r"</?think>", "", delta, flags=re.IGNORECASE)
                    if not delta.strip():
                        return
                    if first_stream_ms is None:
                        first_stream_ms = (time.perf_counter() - input_started) * 1000
                        self._event_bus.publish(
                            "assistant.first_token", {"elapsed_ms": round(first_stream_ms, 3)},
                            source="orchestrator", correlation_id=correlation_id,
                        )
                    self._event_bus.publish(
                        "assistant.response.delta", {"delta": delta}, source="orchestrator",
                        correlation_id=correlation_id,
                    )

                generation_started_ms = (time.perf_counter() - input_started) * 1000
                self._event_bus.publish(
                    "assistant.generation.started", {
                        "estimated_prompt_tokens": context.estimated_tokens,
                        "recent_messages": context.recent_messages_included,
                    }, source="orchestrator", correlation_id=correlation_id,
                )
                generated = self._models.generate(GenerationRequest(
                    messages=context.messages, max_tokens=token_budget,
                    temperature=float(generation.get("temperature", 0.3)),
                    on_token=stream_token,
                ))
                clean_text = re.sub(
                    r"<think>.*?</think>|</?think>", "", generated.text,
                    flags=re.IGNORECASE | re.DOTALL,
                ).strip()
                response_complete_ms = (time.perf_counter() - input_started) * 1000
                response = OrchestratorResponse(
                    bool(clean_text), clean_text or self._message("empty", language.response_language),
                    {
                        "route": route.decision.value, "engine": "ARCHI",
                        "usage": {"prompt_tokens": generated.prompt_tokens, "completion_tokens": generated.completion_tokens},
                        "metrics": {
                            "load_ms": round(generated.load_ms, 3),
                            "first_token_ms": round(generated.first_token_ms, 3) if generated.first_token_ms is not None else None,
                            "total_ms": round(generated.total_ms, 3),
                            "tokens_per_second": self._generation_tokens_per_second(generated),
                            "legacy_end_to_end_tokens_per_second": round(
                                generated.completion_tokens / max(0.001, (generated.total_ms - generated.load_ms) / 1000), 3
                            ),
                            "stages": dict(generated.timings),
                            "end_to_end": {
                                "input_received": 0.0,
                                "routing_complete": round(routing_complete_ms, 3),
                                "context_complete": round(context_complete_ms, 3),
                                "generation_started": round(generation_started_ms, 3),
                                "first_token": round(first_stream_ms, 3) if first_stream_ms is not None else None,
                                "response_complete": round(response_complete_ms, 3),
                            },
                            "context": {
                                "estimated_tokens": context.estimated_tokens,
                                "recent_messages_included": context.recent_messages_included,
                                "recent_messages_dropped": context.recent_messages_dropped,
                            },
                            "response_budget": {
                                "max_tokens": response_budget.max_tokens,
                                "mode": response_budget.mode,
                                "reason": response_budget.reason,
                            },
                        },
                    }, correlation_id,
                )
            except Exception:
                response = OrchestratorResponse(False, self._message("model_error", language.response_language), {}, correlation_id)
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
        self._remember(text, response)
        return response

    def _system_prompt(self, language: str) -> str:
        personality = self._personality_provider()
        now = datetime.now().astimezone()
        current_context = now.strftime("%Y-%m-%d %Z (UTC%z)")
        return (
            "You are ARCHEON, a local desktop assistant. Be accurate, concise, and honest. Never claim an "
            "action, screen or file without a verified tool result. Your intelligence engine is named ARCHI; "
            "never reveal model files, storage paths, credentials or private internals. User settings are "
            "organized as General, Personalization, Activation, Voice and audio, Privacy and data, and ARCHI. "
            "Guide users to the right section when asked. Your creator is Boris Saldarrega, founder of "
            "DZKnight Company; development began in January 2020 as a predefined-message chatbot. "
            "Treat live news and changing facts as unverified unless a live-search tool result is provided. "
            f"Target language: {language}. {response_directive(language)} Personality style: {personality.get('style', 'natural')}; "
            f"detail: {personality.get('detail', 50)}/100; formality: {personality.get('formality', 45)}/100. "
            f"Current local date: {current_context}."
        )

    @staticmethod
    def _generation_tokens_per_second(generated: Any) -> float:
        server = generated.timings.get("server", {}) if isinstance(generated.timings, Mapping) else {}
        measured = server.get("predicted_per_second") if isinstance(server, Mapping) else None
        if isinstance(measured, (int, float)) and measured > 0:
            return round(float(measured), 3)
        generation_ms = generated.timings.get("generation_after_first_content_ms", 0.0) if isinstance(generated.timings, Mapping) else 0.0
        if isinstance(generation_ms, (int, float)) and generation_ms > 0:
            return round(generated.completion_tokens / max(0.001, float(generation_ms) / 1000), 3)
        return round(generated.completion_tokens / max(0.001, (generated.total_ms - generated.load_ms) / 1000), 3)

    @staticmethod
    def _identity_response(normalized: str, correlation_id: str, language: str) -> OrchestratorResponse | None:
        creator_queries = (
            "quien es tu creador", "quien te creo", "quien te ha creado", "tu creador",
            "who created you", "who is your creator", "your creator",
            "quem e seu criador", "quem te criou", "qui est ton createur", "qui t a cree",
            "wer ist dein schopfer", "wer hat dich erschaffen", "chi e il tuo creatore", "chi ti ha creato",
            "谁创造了你", "你的创造者", "あなたを作ったのは誰", "開発者は誰", "누가 너를 만들었", "개발자는 누구",
            "кто твой создатель", "кто тебя создал", "من هو منشئك", "من صنعك", "तुम्हें किसने बनाया", "तुम्हारा निर्माता कौन",
        )
        history_queries = (
            "cuando fuiste creado", "cuando comenzaste", "cuanto tiempo de creacion", "tu historia",
            "when were you created", "when did you start", "your history",
            "quando voce foi criado", "ton histoire", "wann wurdest du erschaffen", "la tua storia",
            "你的历史", "いつ作られた", "언제 만들어졌", "твоя история", "متى تم إنشاؤك", "तुम कब बनाए गए",
        )
        if not any(query in normalized for query in creator_queries + history_queries):
            return None
        message = identity_message(language)
        return OrchestratorResponse(
            True,
            message,
            {"route": "local_identity", "creator": "Boris Saldarrega", "started": "2020-01"},
            correlation_id,
        )

    @staticmethod
    def _product_help_response(normalized: str, correlation_id: str, language: str) -> OrchestratorResponse | None:
        help_intent = is_product_help_request(normalized) or any(term in normalized for term in (
            "ayuda con archeon", "configuracion de archeon", "ajustes de archeon", "archeon settings",
            "ajuda com archeon", "parametres archeon", "archeon einstellungen", "impostazioni archeon",
            "如何更改 archeon", "archeon 设置", "archeon の設定", "archeon 설정",
            "настройки archeon", "إعدادات archeon", "archeon सेटिंग्स",
        ))
        if not help_intent:
            return None
        topics = (
            (("color", "tema", "fondo", "logo", "reloj", "accesibilidad", "apariencia", "theme", "background", "clock", "accessibility", "personnalisation", "hintergrund", "sfondo", "主题", "背景", "テーマ", "배경", "тема", "الخلفية", "थीम"), "personalization"),
            (("activacion", "wake", "nombre para llam", "palabra de activacion", "ativacao", "activation", "aktivierung", "attivazione", "唤醒", "起動", "호출", "активац", "التنشيط", "सक्रियण"), "activation"),
            (("voz", "microfono", "altavoz", "speaker", "voice", "audio", "voix", "stimme", "voce", "语音", "音声", "음성", "голос", "الصوت", "आवाज़"), "voice"),
            (("idioma", "inicio", "arranque", "language", "langue", "sprache", "lingua", "语言", "言語", "언어", "язык", "اللغة", "भाषा"), "general"),
            (("sincron", "privacidad", "datos", "cuenta", "privacy", "confidentialite", "datenschutz", "privacy", "隐私", "プライバシー", "개인정보", "конфиденциаль", "الخصوصية", "गोपनीयता"), "privacy"),
            (("inteligencia", "archi", "rapidez", "personalidad", "cerebro", "corazon", "intelligence", "geschwindigkeit", "速度", "속도", "скорост", "السرعة", "गति"), "intelligence"),
        )
        topic = next((value for terms, value in topics if any(term in normalized for term in terms)), "overview")
        message = product_help_message(language, topic)
        return OrchestratorResponse(True, message, {"route": "product_help", "topic": topic}, correlation_id)

    @staticmethod
    def _from_tool(result: ToolResult, correlation_id: str, language: str = "es") -> OrchestratorResponse:
        if result.ok and result.verified:
            return OrchestratorResponse(True, Orchestrator._message("status", language), result.data, correlation_id)
        return OrchestratorResponse(False, result.error or Orchestrator._message("unverified", language), {}, correlation_id)

    @staticmethod
    def _message(key: str, language: str) -> str:
        return core_message(key, language)
