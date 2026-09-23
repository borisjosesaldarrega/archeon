"""Resolve negation and late self-correction before deterministic actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Pattern


class CommandConfidence(StrEnum):
    DIRECT = "DIRECT"
    CONTEXTUAL = "CONTEXTUAL"
    AMBIGUOUS = "AMBIGUOUS"
    NEGATED = "NEGATED"


@dataclass(frozen=True, slots=True)
class NegationResolution:
    confidence: CommandConfidence
    action_allowed: bool
    negated: bool
    self_corrected: bool
    matched_text: str = ""
    reason: str = ""

    def public(self) -> dict[str, object]:
        return {
            "confidence": self.confidence.value,
            "action_allowed": self.action_allowed,
            "negated": self.negated,
            "self_corrected": self.self_corrected,
            "matched_text": self.matched_text,
            "reason": self.reason,
        }


class NegationScopeResolver:
    """Prefer the user's final expressed intent over an earlier command token."""

    _NEGATION = re.compile(
        r"(?:\b(?:no|nunca|jam[aá]s|sin|don't|do not|never|n[aã]o|nicht|non|не)\b|"
        r"不要|别|しない|하지\s*마|لا|मत)", re.IGNORECASE,
    )
    _RESET = re.compile(
        r"(?:[,;:]|\b(?:pero|sino|however|but|por[eé]m|aber|tuttavia)\b)", re.IGNORECASE,
    )
    _LATE_CANCEL = re.compile(
        r"(?:\b(?:no[,\s]+(?:mejor\s+)?no|mejor\s+no|espera(?:\s+un\s+momento)?[,\s]+no|"
        r"olvida(?:lo|la)?|cancela(?:lo|la)?|cancel that|actually[,\s]+no|never mind)\b|"
        r"\b(?:d[eé]jala|dejala|d[eé]jalo|dejalo)\s+(?:sonando|reproduciendo)\b|"
        r"\bkeep\s+(?:it|the music)\s+playing\b)", re.IGNORECASE,
    )
    _DIRECT_PREFIX = re.compile(
        r"^(?:(?:hola\s+)?archeon(?:,\s*|\s+)(?:por\s+favor)?|por\s+favor|dime|"
        r"(?:quiero|necesito)\s+que|(?:puedes|podr[ií]as))?$",
        re.IGNORECASE,
    )
    _CONTEXT_PREFIX = re.compile(
        r"^(?:ahora|entonces|y|tambi[eé]n)(?:\s+(?:quiero|necesito)\s+que)?$",
        re.IGNORECASE,
    )

    def resolve(
        self,
        text: str,
        action_pattern: str | Pattern[str],
        *,
        context_present: bool = False,
        destructive: bool = False,
        lookbehind_words: int = 6,
    ) -> NegationResolution:
        compiled = re.compile(action_pattern, re.IGNORECASE) if isinstance(action_pattern, str) else action_pattern
        matches = list(compiled.finditer(text))
        if not matches:
            return NegationResolution(CommandConfidence.AMBIGUOUS, False, False, False, reason="action_not_found")

        match = matches[-1]
        prefix_words = re.findall(r"\S+", text[:match.start()])[-max(1, lookbehind_words):]
        prefix = " ".join(prefix_words)
        resets = list(self._RESET.finditer(prefix))
        if resets:
            prefix = prefix[resets[-1].end():]
        suffix = text[match.end():]
        late_cancel = bool(self._LATE_CANCEL.search(suffix))
        negated = bool(self._NEGATION.search(prefix)) or late_cancel
        if negated:
            return NegationResolution(
                CommandConfidence.NEGATED, False, True, late_cancel,
                match.group(0), "late_self_correction" if late_cancel else "negation_in_scope",
            )

        leading = text[:match.start()].strip()
        direct = bool(self._DIRECT_PREFIX.fullmatch(leading))
        contextual = bool(context_present and self._CONTEXT_PREFIX.fullmatch(leading))
        confidence = CommandConfidence.DIRECT if direct else (
            CommandConfidence.CONTEXTUAL if contextual else CommandConfidence.AMBIGUOUS
        )
        allowed = confidence in {CommandConfidence.DIRECT, CommandConfidence.CONTEXTUAL}
        if destructive and confidence is CommandConfidence.AMBIGUOUS:
            allowed = False
        return NegationResolution(
            confidence, allowed, False, False, match.group(0),
            "explicit_command" if direct else "context_resolved" if context_present else "ambiguous_action",
        )
