"""Dependency-free language selection shared by UI, text, voice and agents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import SUPPORTED_LOCALES


@dataclass(frozen=True, slots=True)
class LocaleSpec:
    code: str
    native_name: str
    english_name: str
    direction: str = "ltr"
    primary_langid: int | None = None


LOCALE_SPECS = {
    "es": LocaleSpec("es", "Español", "Spanish", primary_langid=0x0A),
    "en": LocaleSpec("en", "English", "English", primary_langid=0x09),
    "pt": LocaleSpec("pt", "Português", "Portuguese", primary_langid=0x16),
    "fr": LocaleSpec("fr", "Français", "French", primary_langid=0x0C),
    "de": LocaleSpec("de", "Deutsch", "German", primary_langid=0x07),
    "it": LocaleSpec("it", "Italiano", "Italian", primary_langid=0x10),
    "zh": LocaleSpec("zh", "中文", "Chinese", primary_langid=0x04),
    "ja": LocaleSpec("ja", "日本語", "Japanese", primary_langid=0x11),
    "ko": LocaleSpec("ko", "한국어", "Korean", primary_langid=0x12),
    "ru": LocaleSpec("ru", "Русский", "Russian", primary_langid=0x19),
    "ar": LocaleSpec("ar", "العربية", "Arabic", direction="rtl", primary_langid=0x01),
    "hi": LocaleSpec("hi", "हिन्दी", "Hindi", primary_langid=0x39),
}

if tuple(LOCALE_SPECS) != SUPPORTED_LOCALES:
    raise RuntimeError("language_catalog_does_not_match_supported_locales")


_SCRIPT_PATTERNS = (
    ("ar", re.compile(r"[\u0600-\u06ff]")),
    ("ru", re.compile(r"[\u0400-\u052f]")),
    ("hi", re.compile(r"[\u0900-\u097f]")),
    ("ko", re.compile(r"[\uac00-\ud7af]")),
    ("ja", re.compile(r"[\u3040-\u30ff]")),
    ("zh", re.compile(r"[\u3400-\u9fff]")),
)

# High-signal function words and desktop vocabulary. This bounded router is
# intentionally much smaller than a statistical language detector.
_WORDS = {
    "es": frozenset("abre abrir ayuda como dónde donde estado gracias por favor quiero configuración sistema archivo pantalla música reproduce pausa".split()),
    "en": frozenset("open help how where status thanks please want the settings system file screen music play pause".split()),
    "pt": frozenset("abre abrir ajuda como onde estado obrigado por favor quero configurações sistema arquivo tela música reproduzir pausa".split()),
    "fr": frozenset("ouvre ouvrir aide comment où statut merci vous plaît veux paramètres système fichier écran musique lire pause".split()),
    "de": frozenset("öffne öffnen hilfe wie wo status danke bitte möchte einstellungen system datei bildschirm musik abspielen pause".split()),
    "it": frozenset("apri aprire aiuto come dove stato grazie per favore voglio impostazioni sistema file schermo musica riproduci pausa".split()),
}

_LANGUAGE_ALIASES = {
    "es": ("español", "espanol", "spanish"),
    "en": ("english", "inglés", "ingles"),
    "pt": ("português", "portugues", "portuguese"),
    "fr": ("français", "francais", "french"),
    "de": ("deutsch", "german", "alemán", "aleman"),
    "it": ("italiano", "italian"),
    "zh": ("中文", "chinese", "chino", "mandarin"),
    "ja": ("日本語", "japanese", "japonés", "japones"),
    "ko": ("한국어", "korean", "coreano"),
    "ru": ("русский", "russian", "ruso"),
    "ar": ("العربية", "arabic", "árabe", "arabe"),
    "hi": ("हिन्दी", "हिंदी", "hindi"),
}

_RESPONSE_REQUESTS = (
    "responde", "contesta", "reply", "answer", "responda", "réponds", "reponds",
    "summarize", "explain", "explique", "résume", "resume", "antworte", "rispondi",
    "crea", "create", "crie", "crée", "erstelle", "creare", "crear", "gere",
    "回答", "答えて", "대답", "요약", "ответь", "أجب", "اختصر", "जवाब", "सारांश",
)


def normalize_locale(value: str | None, fallback: str = "es") -> str:
    code = (value or "").strip().casefold().replace("_", "-").split("-", 1)[0]
    return code if code in LOCALE_SPECS else fallback


def locale_direction(value: str | None) -> str:
    return LOCALE_SPECS[normalize_locale(value)].direction


def normalize_text(text: str) -> str:
    """Case-fold and remove Latin accents without damaging Arabic/Indic/CJK text."""

    output: list[str] = []
    for char in unicodedata.normalize("NFKC", text).casefold():
        if "LATIN" in unicodedata.name(char, ""):
            output.extend(
                item for item in unicodedata.normalize("NFKD", char)
                if not unicodedata.combining(item)
            )
        else:
            output.append(char)
    return "".join(output)


def _fold(text: str) -> str:
    return normalize_text(text)


@dataclass(frozen=True, slots=True)
class LanguageDecision:
    response_language: str
    detected_language: str | None
    source: str
    confidence: float


class LanguageContextEngine:
    """Choose a response language without loading an AI model."""

    def decide(
        self,
        text: str,
        *,
        preferred: str = "auto",
        previous: str | None = None,
        fallback: str = "es",
    ) -> LanguageDecision:
        explicit = self.explicit_request(text)
        if explicit:
            return LanguageDecision(explicit, self.detect(text), "explicit_request", 1.0)
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
    def explicit_request(text: str) -> str | None:
        folded = _fold(text)
        if not any(_fold(marker) in folded for marker in _RESPONSE_REQUESTS):
            return None
        for code, aliases in _LANGUAGE_ALIASES.items():
            if any(_fold(alias) in folded for alias in aliases):
                return code
        return None

    @staticmethod
    def detect(text: str) -> str | None:
        for language, pattern in _SCRIPT_PATTERNS:
            if pattern.search(text):
                return language
        words = set(re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE))
        if not words:
            return None
        scored = sorted(
            ((len(words & markers), language) for language, markers in _WORDS.items()),
            key=lambda item: (item[0], item[1]), reverse=True,
        )
        if not scored or scored[0][0] < 2:
            return None
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]
