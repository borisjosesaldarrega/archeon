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
    target_name: str = ""


class RemoteIntentParser:
    """Accept direct imperatives only; questions, negations and vague mentions fail closed."""

    _DESKTOP = r"(?:(?:mi|la|el)\s+)?(?:pc|computadora|ordenador|equipo|desktop)"
    _MOBILE = r"(?:(?:mi|el)\s+)?(?:celular|m[oó]vil|tel[eé]fono|android)"
    _NEGATION = re.compile(r"\b(?:no|nunca|jamas|jamás|sin|evita|evitar)\b")
    _QUESTION = re.compile(r"^(?:como|cómo|puedo|podria|podría|que pasa|qué pasa|sabes)\b")

    @staticmethod
    def _device_key(value: str) -> str:
        clean = re.sub(r"[^\w]+", " ", normalize_text(value)).strip()
        generic = {"archeon", "pc", "computadora", "ordenador", "equipo", "desktop", "windows", "celular", "movil", "telefono", "android", "mi", "el", "la"}
        distinctive = [part for part in clean.split() if part not in generic]
        return " ".join(distinctive) or clean

    @staticmethod
    def _distance(left: str, right: str) -> int:
        """Bounded Damerau-Levenshtein distance; adjacent speech/typing swaps cost one."""
        rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
        for i in range(len(left) + 1):
            rows[i][0] = i
        for j in range(len(right) + 1):
            rows[0][j] = j
        for i in range(1, len(left) + 1):
            for j in range(1, len(right) + 1):
                rows[i][j] = min(
                    rows[i - 1][j] + 1,
                    rows[i][j - 1] + 1,
                    rows[i - 1][j - 1] + (left[i - 1] != right[j - 1]),
                )
                if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                    rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
        return rows[-1][-1]

    def _resolve_device(self, label: str, known_devices: dict[str, str]) -> tuple[str, str] | None:
        wanted = self._device_key(label)
        if len(wanted) < 2:
            return None
        scored: list[tuple[int, str, str]] = []
        for name, platform in known_devices.items():
            key = self._device_key(name)
            if wanted == key or wanted == re.sub(r"[^\w]+", " ", normalize_text(name)).strip():
                score = 0
            elif wanted in key.split() or (len(wanted) >= 4 and wanted in key):
                score = 1
            else:
                distance = self._distance(wanted, key)
                allowed = 1 if len(wanted) >= 4 else 0
                if distance > allowed:
                    continue
                score = 2 + distance
            scored.append((score, name, platform))
        scored.sort(key=lambda item: (item[0], item[1]))
        if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
            return None
        return scored[0][1], scored[0][2]

    def parse(self, text: str, known_devices: dict[str, str] | None = None) -> RemoteIntent | None:
        value = normalize_text(text).strip(" .!?¡¿")
        if not value or self._NEGATION.search(value) or self._QUESTION.search(value):
            return None
        if re.fullmatch(rf"(?:apaga|apagar)\s+(?:ahora\s+)?{self._DESKTOP}", value):
            return RemoteIntent(RemoteAction.SHUTDOWN, {}, "desktop", True)
        launch = re.fullmatch(rf"(?:abre|abreme|habre|inicia|ejecuta)\s+(.+?)\s+en\s+({self._DESKTOP}|{self._MOBILE})", value)
        if launch and len(launch.group(1).strip()) >= 2:
            target = "mobile" if re.fullmatch(self._MOBILE, launch.group(2)) else "desktop"
            return RemoteIntent(RemoteAction.LAUNCH, {"query": launch.group(1).strip()}, target, False)
        media = re.fullmatch(rf"(?:reproduce|reprodus|pon|ponme)\s+(.+?)\s+en\s+({self._DESKTOP}|{self._MOBILE})", value)
        if media and len(media.group(1).strip()) >= 2:
            target = "mobile" if re.fullmatch(self._MOBILE, media.group(2)) else "desktop"
            return RemoteIntent(RemoteAction.MEDIA_PLAY, {"query": media.group(1).strip()}, target, False)
        named = re.fullmatch(r"(abre|abreme|habre|inicia|ejecuta|reproduce|reprodus|pon|ponme)\s+(.+?)\s+en\s+([\w .·-]{2,60})", value)
        if not named:
            prefixed = re.fullmatch(r"(?:en\s+)?([\w .·-]{2,60})\s+(abre|abreme|habre|inicia|ejecuta|reproduce|reprodus|pon|ponme)\s+(.+)", value)
            if prefixed:
                named = _NamedCommand(prefixed.group(2), prefixed.group(3), prefixed.group(1))
        if named and known_devices:
            resolved = self._resolve_device(named.group(3).strip(), known_devices)
            if resolved:
                original_name, platform = resolved
                action = RemoteAction.MEDIA_PLAY if named.group(1) in {"reproduce", "reprodus", "pon", "ponme"} else RemoteAction.LAUNCH
                target = "mobile" if platform == "android" else "desktop"
                return RemoteIntent(action, {"query": named.group(2).strip()}, target, False, original_name)
        return None


class _NamedCommand:
    """Small Match-compatible adapter for target-first natural commands."""

    def __init__(self, verb: str, query: str, target: str) -> None:
        self._groups = (verb, query, target)

    def group(self, index: int) -> str:
        return self._groups[index - 1]
