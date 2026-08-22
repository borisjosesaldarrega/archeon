"""Small, dependency-free language context selection for ARCHEON responses."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import SUPPORTED_LOCALES


_SCRIPT_PATTERNS = (
    ("ar", re.compile(r"[\u0600-\u06ff]")),
    ("ru", re.compile(r"[\u0400-\u04ff]")),
    ("hi", re.compile(r"[\u0900-\u097f]")),
    ("ko", re.compile(r"[\uac00-\ud7af]")),
    ("ja", re.compile(r"[\u3040-\u30ff]")),
    ("zh", re.compile(r"[\u3400-\u9fff]")),
)

_WORDS = {
    "es": {"abre", "ayuda", "cómo", "dónde", "estado", "gracias", "por", "favor", "quiero"},
    "en": {"open", "help", "how", "where", "status", "thanks", "please", "want", "the"},
    "pt": {"abrir", "ajuda", "como", "onde", "obrigado", "por", "favor", "quero"},
    "fr": {"ouvre", "aide", "comment", "où", "merci", "s'il", "veux", "le"},
    "de": {"öffne", "hilfe", "wie", "wo", "danke", "bitte", "möchte", "der"},
    "it": {"apri", "aiuto", "come", "dove", "grazie", "favore", "voglio", "il"},
}

_EXPLICIT = re.compile(
    r"(?:responde|contesta|reply|answer|réponds|antworte|rispondi)\s+(?:en|in|auf)?\s*"
    r"(español|spanish|english|inglés|português|portuguese|français|french|deutsch|german|italiano|italian)",
    re.IGNORECASE,
)
_EXPLICIT_CODES = {
    "español": "es", "spanish": "es", "english": "en", "inglés": "en",
    "português": "pt", "portuguese": "pt", "français": "fr", "french": "fr",
    "deutsch": "de", "german": "de", "italiano": "it", "italian": "it",
}


@dataclass(frozen=True, slots=True)
class LanguageDecision:
    response_language: str
    detected_language: str | None
    source: str
    confidence: float


class LanguageContextEngine:
    """Choose response language without loading a model or changing UI language."""

    def decide(
        self,
        text: str,
        *,
        preferred: str = "auto",
        previous: str | None = None,
        fallback: str = "es",
    ) -> LanguageDecision:
        explicit = _EXPLICIT.search(text)
        if explicit:
            language = _EXPLICIT_CODES[explicit.group(1).lower()]
            return LanguageDecision(language, self.detect(text), "explicit_request", 1.0)
        detected = self.detect(text)
        if detected:
            return LanguageDecision(detected, detected, "current_message", 0.86)
        if preferred in SUPPORTED_LOCALES:
            return LanguageDecision(preferred, None, "preference", 0.7)
        if previous in SUPPORTED_LOCALES:
            return LanguageDecision(str(previous), None, "conversation_context", 0.6)
        selected = fallback if fallback in SUPPORTED_LOCALES else "es"
        return LanguageDecision(selected, None, "fallback", 0.4)

    @staticmethod
    def detect(text: str) -> str | None:
        for language, pattern in _SCRIPT_PATTERNS:
            if pattern.search(text):
                return language
        words = set(re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE))
        if not words:
            return None
        scored = sorted(
            ((len(words & markers), language) for language, markers in _WORDS.items()),
            reverse=True,
        )
        return scored[0][1] if scored and scored[0][0] >= 2 else None
