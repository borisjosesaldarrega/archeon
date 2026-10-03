"""Semantic location slots and explicit location-memory consent."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _fold(value: str) -> str:
    plain = "".join(
        character for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", plain, re.UNICODE))


@dataclass(frozen=True, slots=True)
class LocationMemoryResolution:
    location: str
    confidence: float
    evidence: tuple[str, ...]


class LocationMemoryResolver:
    """Extract a location only when the user also grants memory consent."""

    MEMORY_CONCEPTS = frozenset({"guarda", "guardar", "recuerda", "recordar", "memoriza", "conserva", "save", "remember"})
    LOCATION_CONCEPTS = frozenset({"ubicacion", "ciudad", "lugar", "location", "city"})
    FUTURE_CONCEPTS = frozenset({"proxima", "futuro", "despues", "siempre", "next", "future"})
    CONNECTORS = frozenset({"asi", "entonces", "para", "porque", "y"})
    TRAILING_WORDS = MEMORY_CONCEPTS | LOCATION_CONCEPTS | FUTURE_CONCEPTS | CONNECTORS | frozenset({"mi", "la", "lo", "que"})

    def resolve(self, text: str) -> LocationMemoryResolution | None:
        normalized = _fold(text)
        tokens = normalized.split()
        memory = set(tokens) & self.MEMORY_CONCEPTS
        location = set(tokens) & self.LOCATION_CONCEPTS
        if not memory or not location:
            return None
        boundary = min(
            (tokens.index(token) for token in tokens if token in memory),
            default=len(tokens),
        )
        leading = [token for token in tokens[:boundary] if token not in self.TRAILING_WORDS]
        explicit = re.search(r"(?:ubicacion|ciudad|lugar)\s+(?:es|sera)\s+([\w\s-]{2,80})", normalized)
        candidate = " ".join(leading).strip() or (explicit.group(1).strip() if explicit else "")
        candidate = re.sub(r"\b(?:asi que|entonces|para la proxima|para el futuro)\b.*$", "", candidate).strip()
        if not candidate or len(candidate) > 80:
            return None
        future = set(tokens) & self.FUTURE_CONCEPTS
        score = min(0.99, 0.72 + (0.12 if future else 0.0) + (0.08 if len(candidate.split()) <= 4 else 0.0))
        evidence = (*sorted(f"memory:{item}" for item in memory), *sorted(f"location:{item}" for item in location))
        return LocationMemoryResolution(candidate.title(), score, evidence)
