"""Conservative mobile-to-device intent parsing with negative guards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from archeon.core.language import normalize_text

from .models import RemoteAction


@dataclass(frozen=True, slots=True)
class RemoteIntent:
    action: RemoteAction
    arguments: dict[str, Any]
    target_kind: str
    confirmation_required: bool


class RemoteIntentParser:
    """Accept direct imperatives only; questions, negations and vague mentions fail closed."""

    _TARGET = r"(?:(?:mi|la|el)\s+)?(?:pc|computadora|ordenador|equipo)"
    _NEGATION = re.compile(r"\b(?:no|nunca|jamas|jamás|sin|evita|evitar)\b")
    _QUESTION = re.compile(r"^(?:como|cómo|puedo|podria|podría|que pasa|qué pasa|sabes)\b")

    def parse(self, text: str) -> RemoteIntent | None:
        value = normalize_text(text).strip(" .!?¡¿")
        if not value or self._NEGATION.search(value) or self._QUESTION.search(value):
            return None
        if re.fullmatch(rf"(?:apaga|apagar)\s+(?:ahora\s+)?{self._TARGET}", value):
            return RemoteIntent(RemoteAction.SHUTDOWN, {}, "desktop", True)
        launch = re.fullmatch(rf"(?:abre|inicia|ejecuta)\s+(.+?)\s+en\s+{self._TARGET}", value)
        if launch and len(launch.group(1).strip()) >= 2:
            return RemoteIntent(RemoteAction.LAUNCH, {"query": launch.group(1).strip()}, "desktop", False)
        media = re.fullmatch(rf"(?:reproduce|pon)\s+(.+?)\s+en\s+{self._TARGET}", value)
        if media and len(media.group(1).strip()) >= 2:
            return RemoteIntent(RemoteAction.MEDIA_PLAY, {"query": media.group(1).strip()}, "desktop", False)
        return None
