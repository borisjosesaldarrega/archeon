"""Bounded conversation context with no background process or embeddings."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Mapping, Sequence


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate for multilingual prompt budgeting."""
    return max(1, (len(text) + 2) // 3)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    messages: tuple[Mapping[str, str], ...]
    estimated_tokens: int
    recent_messages_included: int
    recent_messages_dropped: int


@dataclass(frozen=True, slots=True)
class ResponseBudget:
    max_tokens: int
    mode: str
    reason: str


class ResponseBudgetManager:
    """Allocate output tokens from intent instead of always reserving 512."""

    _DETAIL = (
        "explica detalladamente", "paso a paso", "en detalle", "respuesta larga",
        "explain in detail", "step by step", "detailed answer", "em detalhe",
        "étape par étape", "ausführlich", "passo dopo passo", "详细", "詳しく",
        "자세히", "подробно", "بالتفصيل", "विस्तार से",
    )
    _SHORT = (
        "solo el nombre", "respuesta corta", "breve", "just the name", "short answer",
        "apenas o nome", "réponse courte", "kurz", "risposta breve", "只回答", "短く",
        "짧게", "кратко", "باختصار", "संक्षेप में",
    )

    def allocate(self, text: str, *, configured_max: int, detail: int = 50) -> ResponseBudget:
        normalized = text.casefold()
        ceiling = max(32, min(4096, int(configured_max)))
        if any(term in normalized for term in self._SHORT):
            return ResponseBudget(min(64, ceiling), "concise", "explicit_concise_request")
        if any(term in normalized for term in self._DETAIL):
            return ResponseBudget(min(768, ceiling), "detailed", "explicit_detail_request")
        normal = max(96, min(224, 80 + max(0, min(100, int(detail))) * 2))
        return ResponseBudget(min(normal, ceiling), "normal", "personality_detail_budget")


class ContextOptimizer:
    """Remove redundant history and bound individual turns before prompt eval."""

    def optimize(self, messages: Sequence[Mapping[str, str]], *, per_message_tokens: int = 512) -> tuple[Mapping[str, str], ...]:
        limit_chars = max(192, int(per_message_tokens) * 3)
        optimized: list[dict[str, str]] = []
        previous: tuple[str, str] | None = None
        for message in messages:
            role = str(message.get("role", "user"))
            content = " ".join(str(message.get("content", "")).split())
            if not content:
                continue
            identity = (role, content.casefold())
            if identity == previous:
                continue
            previous = identity
            if len(content) > limit_chars:
                head = int(limit_chars * .68)
                tail = limit_chars - head
                content = content[:head].rstrip() + " … " + content[-tail:].lstrip()
            optimized.append({"role": role, "content": content})
        return tuple(optimized)


class ConversationMemory:
    """Small in-memory recent-turn buffer; persistence/RAG remain separate layers."""

    def __init__(self, max_messages: int = 24) -> None:
        self._messages: deque[dict[str, str]] = deque(maxlen=max(2, min(100, max_messages)))
        self._lock = RLock()

    def add_turn(self, user: str, assistant: str) -> None:
        with self._lock:
            self._messages.append({"role": "user", "content": user.strip()})
            self._messages.append({"role": "assistant", "content": assistant.strip()})

    def recent(self, turns: int) -> tuple[Mapping[str, str], ...]:
        count = max(0, min(20, int(turns))) * 2
        with self._lock:
            return tuple(list(self._messages)[-count:]) if count else ()

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()


class ContextBudgetManager:
    """Compose stable system + relevant recent context within a hard prompt budget."""

    def build(
        self,
        *,
        system: str,
        user: str,
        recent_conversation: Sequence[Mapping[str, str]] = (),
        max_prompt_tokens: int = 3072,
    ) -> ContextBudget:
        limit = max(256, int(max_prompt_tokens))
        original_count = len(recent_conversation)
        recent_conversation = ContextOptimizer().optimize(recent_conversation)
        system_message = {"role": "system", "content": system}
        user_message = {"role": "user", "content": user}
        mandatory = estimate_tokens(system) + estimate_tokens(user)
        remaining = max(0, limit - mandatory)
        selected: list[Mapping[str, str]] = []
        for message in reversed(tuple(recent_conversation)):
            content = str(message.get("content", ""))
            cost = estimate_tokens(content)
            if cost > remaining:
                continue
            selected.append({"role": str(message.get("role", "user")), "content": content})
            remaining -= cost
        selected.reverse()
        messages = (system_message, *selected, user_message)
        return ContextBudget(
            messages=messages,
            estimated_tokens=sum(estimate_tokens(str(item["content"])) for item in messages),
            recent_messages_included=len(selected),
            recent_messages_dropped=max(0, original_count - len(selected)),
        )
