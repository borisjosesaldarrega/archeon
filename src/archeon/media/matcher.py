"""Provider-neutral music intent parsing and candidate ranking."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from .providers import MediaSearchResult
from archeon.core.language import normalize_text


VARIANTS = {
    "remix": ("remix", "mix", "bootleg", "rework", "mashup", "flip"),
    "live": ("live", "en vivo", "concert", "concierto"),
    "acoustic": ("acoustic", "acustica", "acustico"),
    "instrumental": ("instrumental", "karaoke"),
    "slowed": ("slowed", "slowed reverb"),
    "sped_up": ("sped up", "nightcore"),
    "edit": ("edit", "radio edit", "extended"),
    "remaster": ("remaster", "remastered"),
    "cover": ("cover", "tribute", "tributo"),
    "version": ("version", "version alternativa"),
}
STOP_WORDS = {"pon", "poner", "reproduce", "toca", "play", "reproduza", "joue", "spiele", "riproduci"}
UNKNOWN_ARTISTS = frozenset({
    "", "anonimo", "anonymous", "unknown", "unknown artist", "artista desconocido", "artista local",
})

PLAY_PREFIX = re.compile(
    r"^(?:archeon[\s,]+)?(?:pon(?:me)?|reproduce|toca|play|reproduza|toque|joue|lis|spiele|"
    r"riproduci|metti|播放|再生|재생|включи|воспроизведи|شغّل|شغل|قم\s+بتشغيل|चलाओ|बजाओ)\s*"
    r"(?:(?:la\s+canci[oó]n|a\s+m[uú]sica|la\s+chanson|das\s+lied|la\s+canzone|歌曲|曲|노래|песню|الأغنية|गाना)\s+)?",
    flags=re.IGNORECASE,
)


def normalize(value: str) -> str:
    plain = normalize_text(value)
    plain = re.sub(r"\b(?:feat|ft|featuring)\.?\s+", " ", plain)
    return " ".join("".join(char if char.isalnum() else " " for char in plain).split())


def is_unknown_artist(value: str) -> bool:
    """Identify provider placeholders without guessing a replacement artist."""
    return normalize(value) in UNKNOWN_ARTISTS


def detect_variant(value: str) -> str | None:
    normalized = normalize(value)
    for variant, terms in VARIANTS.items():
        if any(re.search(rf"\b{re.escape(normalize(term))}\b", normalized) for term in terms):
            return variant
    return None


def _strip_variant(value: str) -> str:
    result = normalize(value)
    for terms in VARIANTS.values():
        for term in sorted(terms, key=len, reverse=True):
            result = re.sub(rf"\b{re.escape(normalize(term))}\b", " ", result)
    result = re.sub(
        r"\b(?:official\s+(?:music\s+)?video|official\s+audio|video\s+oficial|audio\s+oficial|"
        r"video\s+musical|lyric\s+video|lyrics?|letra|visuali[sz]er|topic)\b",
        " ", result,
    )
    return " ".join(result.split())


@dataclass(frozen=True, slots=True)
class MediaSearchQuery:
    title: str
    artist: str = ""
    album: str = ""
    requested_version: str = "original"
    allow_alternatives: bool = False

    @classmethod
    def parse(cls, command: str) -> "MediaSearchQuery":
        value = PLAY_PREFIX.sub("", command.strip()).strip(" .!?¡¿")
        normalized = normalize(value)
        any_version = any(term in normalized for term in ("cualquier version", "cualquiera version", "any version"))
        requested_version = "original" if any_version else (detect_variant(normalized) or "original")
        allow_alternatives = any_version or requested_version != "original"
        cleaned = value
        if any_version:
            cleaned = re.sub(r"^(?:cualquier|cualquiera|any)\s+versi[oó]n\s+de\s+", "", cleaned, flags=re.IGNORECASE)
        elif requested_version != "original":
            all_terms = sorted(
                {term for terms in VARIANTS.values() for term in terms} | {"en vivo", "concierto", "acústica", "acústico"},
                key=len, reverse=True,
            )
            cleaned = re.sub(
                rf"^(?:(?:el|la|un|una)\s+)?(?:(?:versi[oó]n)\s+)?(?:{'|'.join(re.escape(term) for term in all_terms)})\s+(?:de\s+)?",
                "", cleaned, flags=re.IGNORECASE,
            )
        # The conventional dash form is ``artist - title``. Keep natural
        # language forms (``title de artist`` / ``title by artist``) in their
        # original order.
        dash_parts = re.split(r"\s+[—-]\s+", cleaned, maxsplit=1)
        if len(dash_parts) == 2:
            artist = dash_parts[0].strip(" -")
            title = dash_parts[1].strip(" -")
        else:
            parts = re.split(
                r"\s+(?:de|by|do|da|du|von|di|от|من|द्वारा)\s+",
                cleaned, maxsplit=1, flags=re.IGNORECASE,
            )
            title = parts[0].strip(" -")
            artist = parts[1].strip(" -") if len(parts) == 2 else ""
        return cls(title=title, artist=artist, requested_version=requested_version, allow_alternatives=allow_alternatives)

    @property
    def provider_query(self) -> str:
        return " ".join(part for part in (self.title, self.artist) if part).strip()


@dataclass(frozen=True, slots=True)
class MediaCandidateScore:
    candidate: MediaSearchResult
    total: float
    title_similarity: float
    artist_similarity: float
    official_score: float
    original_score: float
    version_penalty: float
    provider_confidence: float
    detected_version: str | None

    @property
    def is_alternative(self) -> bool:
        return self.detected_version is not None and self.detected_version != "original"


def score_candidate(query: MediaSearchQuery, candidate: MediaSearchResult) -> MediaCandidateScore:
    wanted_title = normalize(query.title)
    candidate_title = normalize(candidate.title)
    candidate_base = _strip_variant(candidate.title)
    if query.artist:
        artist_prefix = normalize(query.artist)
        candidate_base = re.sub(rf"^{re.escape(artist_prefix)}\s+", "", candidate_base).strip()
    title_similarity = max(
        SequenceMatcher(None, wanted_title, candidate_title).ratio(),
        SequenceMatcher(None, wanted_title, candidate_base).ratio(),
    )
    wanted_artist = normalize(query.artist)
    artist_similarity = SequenceMatcher(None, wanted_artist, normalize(candidate.artist)).ratio() if wanted_artist else 0.0
    detected = detect_variant(candidate.title)
    requested = query.requested_version
    version_penalty = 0.0
    exact_title = wanted_title == candidate_title or wanted_title == candidate_base
    exact_artist = bool(wanted_artist) and wanted_artist == normalize(candidate.artist)
    original_score = (45.0 if detected is None else 0.0) + (35.0 if exact_title else 0.0)
    if requested == "original" and detected is not None:
        severity = {"live": -95.0, "remaster": -35.0, "acoustic": -90.0}.get(detected, -140.0)
        version_penalty = severity
    elif requested != "original":
        version_penalty = 30.0 if detected == requested else -70.0
    official_score = 30.0 if candidate.is_verified_artist else 0.0
    if exact_artist:
        official_score += 45.0
    elif wanted_artist and artist_similarity >= 0.90:
        official_score += 25.0
    provider_confidence = {"local": 18.0, "jamendo": 10.0, "audius": 10.0, "legacy_local": 8.0}.get(candidate.provider, 5.0)
    duration_score = -30.0 if candidate.duration_ms and candidate.duration_ms < 60_000 else -15.0 if candidate.duration_ms > 15 * 60_000 else 0.0
    popularity_score = min(8.0, math.log10(max(1, candidate.popularity)) * 1.5)
    artist_component = (artist_similarity * 55.0 - (65.0 if artist_similarity < 0.45 else 0.0)) if wanted_artist else 0.0
    total = title_similarity * 100.0 + artist_component + official_score + original_score + version_penalty + provider_confidence + duration_score + popularity_score
    return MediaCandidateScore(
        candidate=candidate, total=round(total, 4), title_similarity=title_similarity,
        artist_similarity=artist_similarity, official_score=official_score,
        original_score=original_score, version_penalty=version_penalty,
        provider_confidence=provider_confidence, detected_version=detected,
    )


def rank_candidates(query: MediaSearchQuery, candidates: Sequence[MediaSearchResult]) -> list[MediaCandidateScore]:
    ranked = [score_candidate(query, candidate) for candidate in candidates]
    canonical_original_exists = any(
        item.detected_version is None and item.title_similarity >= 0.88
        and (not query.artist or item.artist_similarity >= 0.78)
        for item in ranked
    )
    ranked.sort(key=lambda item: (
        1 if canonical_original_exists and query.requested_version == "original" and item.detected_version is not None else 0,
        -item.total, -item.title_similarity, item.candidate.title.casefold(),
    ))
    return ranked
