"""Small deterministic relevance gate for bounded conversation history."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


@dataclass(frozen=True, slots=True)
class TopicDecision:
    topic: str
    explicit_switch: bool
    contextual_reference: bool


class ContextRelevanceGate:
    """Keep useful recent turns without making tool/media state global context."""

    _SWITCH = re.compile(r"\b(?:otra cosa|cambiando de tema|dejando eso|new topic|changing topic|anyway)\b")
    _REFERENCE = re.compile(
        r"\b(?:esa|ese|eso|ella|el anterior|la anterior|otra de|sube(?:lo)?|baja(?:lo)?|"
        r"that one|the previous|another by|it louder|it quieter)\b"
    )
    _TOPICS = {
        "media": re.compile(r"\b(?:cancion|musica|reproduce|ponme|artista|album|remix|spotify|youtube|play|song|music)\b"),
        "translation": re.compile(r"\b(?:en ingles|en espanol|traduce|traducir|como se dice|translate|translation|english practice|practica en ingles)\b"),
        "news": re.compile(r"\b(?:noticia|noticias|hoy|ayer|actualmente|ultima|ultimo|latest|news|today|current)\b"),
        "document": re.compile(r"\b(?:pdf|documento|word|archivo|pagina|resume|docx|document|file)\b"),
        "computer": re.compile(r"\b(?:pantalla|ventana|haz clic|configuracion|mi pc|screen|window|click|settings)\b"),
        "coding": re.compile(r"\b(?:codigo|proyecto|programa|python|javascript|error de compilacion|code|project|debug|compile)\b"),
    }

    def decide(self, text: str) -> TopicDecision:
        normalized = _normalized(text)
        topic = next((name for name, pattern in self._TOPICS.items() if pattern.search(normalized)), "general")
        return TopicDecision(topic, bool(self._SWITCH.search(normalized)), bool(self._REFERENCE.search(normalized)))

    def filter(
        self, current_text: str, messages: Sequence[Mapping[str, str]],
    ) -> tuple[Mapping[str, str], ...]:
        current = self.decide(current_text)
        if current.explicit_switch:
            return ()
        if current.contextual_reference:
            return tuple(messages)
        selected: list[Mapping[str, str]] = []
        pending_user: Mapping[str, str] | None = None
        for message in messages:
            if str(message.get("role")) == "user":
                pending_user = message
                continue
            if pending_user is None:
                continue
            previous = self.decide(str(pending_user.get("content", "")))
            if previous.topic == current.topic or previous.topic == "general" == current.topic:
                selected.extend((pending_user, message))
            pending_user = None
        return tuple(selected)
