"""Lightweight contextual recovery for short voice commands.

The resolver is deliberately independent of an STT engine and of the launcher.
It only corrects a transcript when it contains an explicit launch intention and
the correction can be grounded in a caller-provided catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Iterable, Mapping


_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")
_LAUNCH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("abre", "open"), ("abrir", "open"), ("inicia", "open"),
    ("iniciar", "open"), ("ejecuta", "open"), ("ejecutar", "open"),
    ("lanza", "open"), ("lanzar", "open"), ("open", "open"),
    ("launch", "open"), ("start", "open"), ("ouvre", "open"),
    ("ouvrir", "open"), ("demarre", "open"),
)
_POLITE_SUFFIXES = (" por favor", " please", " s il te plait")


def normalize_speech(value: str) -> str:
    """Return an accent/punctuation-insensitive comparison form."""
    folded = unicodedata.normalize("NFKD", str(value).casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return _SPACE_RE.sub(" ", " ".join(_WORD_RE.findall(ascii_text))).strip()


def _phonetic_key(value: str) -> str:
    """Small multilingual-ish key for common Spanish STT confusions."""
    text = normalize_speech(value)
    replacements = (
        ("ph", "f"), ("qu", "k"), ("gue", "ge"), ("gui", "gi"),
        ("ch", "x"), ("ll", "y"), ("v", "b"), ("z", "s"),
        ("ce", "se"), ("ci", "si"), ("q", "k"), ("c", "k"),
        ("h", ""), ("y", "i"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    # Repeated sounds are rarely meaningful in product names but often appear
    # in noisy hypotheses.
    return re.sub(r"(.)\1+", r"\1", text.replace(" ", ""))


def _brand_sound_key(value: str) -> str:
    """Coarse consonant key for short names commonly mangled by STT."""
    compact = _phonetic_key(value)
    consonants = re.sub(r"[aeiou]", "", compact)
    return re.sub(r"[mn]", "n", consonants)


@dataclass(frozen=True, slots=True)
class SpeechTarget:
    """One app/game/shortcut known by the caller."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    kind: str = "app"


@dataclass(frozen=True, slots=True)
class SpeechAlternative:
    target_id: str
    name: str
    kind: str
    score: float
    matched_alias: str


@dataclass(frozen=True, slots=True)
class SpeechContextResult:
    original_text: str
    normalized_text: str
    command: str
    wake_detected: bool
    intent: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    target_kind: str | None = None
    confidence: float = 0.0
    ambiguous: bool = False
    corrected_text: str | None = None
    alternatives: tuple[SpeechAlternative, ...] = field(default_factory=tuple)
    reason: str = "no_contextual_correction"

    @property
    def matched(self) -> bool:
        return self.target_id is not None and not self.ambiguous


class SpeechContextResolver:
    """Resolve wake phrases and grounded launcher commands without I/O."""

    def __init__(
        self,
        targets: Iterable[SpeechTarget | Mapping[str, Any] | Any] = (),
        *,
        wake_name: str = "Archeon",
        match_threshold: float = 0.78,
        ambiguity_margin: float = 0.055,
    ) -> None:
        self.wake_name = str(wake_name).strip() or "Archeon"
        self.match_threshold = max(0.6, min(float(match_threshold), 0.98))
        self.ambiguity_margin = max(0.01, min(float(ambiguity_margin), 0.2))
        self._targets = tuple(self._coerce_target(value) for value in targets)

    @staticmethod
    def _coerce_target(value: SpeechTarget | Mapping[str, Any] | Any) -> SpeechTarget:
        if isinstance(value, SpeechTarget):
            return value
        if isinstance(value, Mapping):
            aliases = value.get("aliases", ())
            if isinstance(aliases, str):
                aliases = (aliases,)
            return SpeechTarget(
                id=str(value.get("id", value.get("name", ""))),
                name=str(value.get("name", "")),
                aliases=tuple(str(alias) for alias in aliases if str(alias).strip()),
                kind=str(value.get("kind", "app")),
            )
        aliases = getattr(value, "aliases", ())
        if isinstance(aliases, str):
            aliases = (aliases,)
        return SpeechTarget(
            id=str(getattr(value, "id", getattr(value, "name", ""))),
            name=str(getattr(value, "name", "")),
            aliases=tuple(str(alias) for alias in aliases),
            kind=str(getattr(value, "kind", "app")),
        )

    @staticmethod
    def _wake_forms(wake_name: str) -> tuple[str, ...]:
        normalized = normalize_speech(wake_name)
        compact = normalized.replace(" ", "")
        forms = {normalized, compact}
        if len(compact) >= 6:
            # Covers STT word-boundary errors such as “Archi on”/“Arche on”
            # without accepting unrelated words that merely contain the name.
            for split in range(4, len(compact) - 1):
                forms.add(f"{compact[:split]} {compact[split:]}")
        if compact == "archeon":
            forms.update(("arqueon", "archion", "archi on", "arche on"))
        return tuple(sorted(forms, key=len, reverse=True))

    @classmethod
    def split_wake_command(cls, text: str, wake_name: str = "Archeon") -> tuple[bool, str]:
        """Separate a leading wake name; wake-like text elsewhere is untouched."""
        normalized = normalize_speech(text)
        for form in cls._wake_forms(wake_name):
            if normalized == form:
                return True, ""
            if normalized.startswith(form + " "):
                return True, normalized[len(form):].strip()
        return False, normalized

    @staticmethod
    def _extract_intent(command: str) -> tuple[str | None, str]:
        for prefix, intent in _LAUNCH_PREFIXES:
            if command == prefix:
                return intent, ""
            if command.startswith(prefix + " "):
                query = command[len(prefix):].strip()
                for suffix in _POLITE_SUFFIXES:
                    if query.endswith(suffix):
                        query = query[:-len(suffix)].strip()
                return intent, query
        return None, command

    @staticmethod
    def _similarity(query: str, candidate: str) -> float:
        exact_query, exact_candidate = normalize_speech(query), normalize_speech(candidate)
        if not exact_query or not exact_candidate:
            return 0.0
        if exact_query == exact_candidate:
            return 1.0
        orthographic = SequenceMatcher(None, exact_query, exact_candidate).ratio()
        phonetic = SequenceMatcher(None, _phonetic_key(exact_query), _phonetic_key(exact_candidate)).ratio()
        brand_sound = SequenceMatcher(None, _brand_sound_key(exact_query), _brand_sound_key(exact_candidate)).ratio()
        query_tokens, candidate_tokens = set(exact_query.split()), set(exact_candidate.split())
        overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens | candidate_tokens), 1)
        containment = 0.92 if exact_query in exact_candidate or exact_candidate in exact_query else 0.0
        return max(
            containment,
            brand_sound * 0.82,
            phonetic * 0.90,
            orthographic * 0.58 + phonetic * 0.34 + overlap * 0.08,
        )

    def resolve(
        self,
        transcript: str,
        *,
        targets: Iterable[SpeechTarget | Mapping[str, Any] | Any] | None = None,
        wake_name: str | None = None,
        require_wake: bool = False,
    ) -> SpeechContextResult:
        """Resolve a transcript, correcting only a grounded launch target."""
        original = str(transcript)
        normalized = normalize_speech(original)
        wake_detected, command = self.split_wake_command(original, wake_name or self.wake_name)
        if require_wake and not wake_detected:
            return SpeechContextResult(original, normalized, command, False, reason="wake_not_detected")

        intent, query = self._extract_intent(command)
        if intent != "open" or not query:
            return SpeechContextResult(
                original, normalized, command, wake_detected, intent=intent,
                reason="missing_launch_intent" if intent is None else "missing_target",
            )

        catalog = self._targets if targets is None else tuple(self._coerce_target(value) for value in targets)
        scored: list[SpeechAlternative] = []
        for target in catalog:
            if not target.id or not target.name:
                continue
            best_alias, best_score = target.name, 0.0
            for alias in (target.name, *target.aliases):
                score = self._similarity(query, alias)
                if score > best_score:
                    best_alias, best_score = alias, score
            if best_score >= self.match_threshold:
                scored.append(SpeechAlternative(target.id, target.name, target.kind, best_score, best_alias))
        scored.sort(key=lambda value: (-value.score, normalize_speech(value.name), value.target_id))
        alternatives = tuple(scored[:3])
        if not alternatives:
            return SpeechContextResult(
                original, normalized, command, wake_detected, intent=intent,
                reason="no_grounded_match",
            )

        first = alternatives[0]
        ambiguous = len(alternatives) > 1 and first.score - alternatives[1].score < self.ambiguity_margin
        if ambiguous:
            return SpeechContextResult(
                original, normalized, command, wake_detected, intent=intent,
                confidence=first.score, ambiguous=True, alternatives=alternatives,
                reason="ambiguous_target",
            )
        return SpeechContextResult(
            original, normalized, command, wake_detected, intent=intent,
            target_id=first.target_id, target_name=first.name, target_kind=first.kind,
            confidence=first.score, corrected_text=f"{intent} {first.name}",
            alternatives=alternatives, reason="contextual_match",
        )


__all__ = [
    "SpeechAlternative", "SpeechContextResolver", "SpeechContextResult",
    "SpeechTarget", "normalize_speech",
]
