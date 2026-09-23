"""Central voice model/profile catalog; model names are not spread through the app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SpeechModelSpec:
    id: str
    provider: str
    languages: tuple[str, ...]
    directory: str


@dataclass(frozen=True, slots=True)
class VoiceRuntimeProfile:
    name: str
    model_id: str
    vad_mode: int
    silence_ms: int
    max_utterance_ms: int


@dataclass(frozen=True, slots=True)
class VoiceStyleSpec:
    """Provider-neutral description of a speaking style.

    ``rate_delta`` and ``pitch`` are intentionally modest hints. Providers may
    implement them natively, approximate them, or degrade to ``fallback``.
    """

    id: str
    display_name: str
    rate_delta: int = 0
    pitch: str | None = None
    fallback: str = "natural"


MODELS = {
    "vosk-small-es": SpeechModelSpec(
        id="vosk-small-es",
        provider="vosk",
        languages=("es",),
        directory="vosk-model-small-es-0.42",
    ),
}

LOCALE_MODEL_PREFIX = {
    "es": "es", "en": "en-us", "pt": "pt", "fr": "fr", "de": "de",
    "it": "it", "zh": "cn", "ja": "ja", "ko": "ko", "ru": "ru",
    "ar": "ar", "hi": "hi",
}

PROFILES = {
    "eco": VoiceRuntimeProfile("eco", "vosk-small-es", 3, 600, 10_000),
    "balanced": VoiceRuntimeProfile("balanced", "vosk-small-es", 2, 700, 12_000),
    "performance": VoiceRuntimeProfile("performance", "vosk-small-es", 1, 800, 15_000),
}


VOICE_STYLES = {
    "natural": VoiceStyleSpec("natural", "Natural"),
    "deep": VoiceStyleSpec("deep", "Deep", -1, "-3"),
    "technological": VoiceStyleSpec("technological", "Technological", 1, "+1"),
    "warm": VoiceStyleSpec("warm", "Warm", -1, "-1"),
    "professional": VoiceStyleSpec("professional", "Professional"),
    "energetic": VoiceStyleSpec("energetic", "Energetic", 2, "+1"),
    "calm": VoiceStyleSpec("calm", "Calm", -2, "-1"),
    "cinematic": VoiceStyleSpec("cinematic", "Cinematic", -2, "-3"),
    # Custom is a stable public choice. A provider without a custom-style
    # implementation must degrade safely instead of failing synthesis.
    "custom": VoiceStyleSpec("custom", "Custom", fallback="natural"),
}

VOICE_STYLE_ALIASES = {
    "deep_tech": "deep",
    "crisp": "technological",
    "tech": "technological",
}


def resolve_voice_style(
    style: str | None,
    supported: Iterable[str] | None = None,
) -> VoiceStyleSpec:
    """Resolve a style and safely degrade it for a provider's capabilities."""

    requested = (style or "natural").strip().casefold().replace("-", "_")
    requested = VOICE_STYLE_ALIASES.get(requested, requested)
    spec = VOICE_STYLES.get(requested, VOICE_STYLES["natural"])
    if supported is None:
        return spec
    available = {item.casefold() for item in supported}
    if spec.id in available:
        return spec
    fallback = VOICE_STYLES.get(spec.fallback, VOICE_STYLES["natural"])
    return fallback if fallback.id in available else VOICE_STYLES["natural"]


def resolve_profile(name: str) -> VoiceRuntimeProfile:
    return PROFILES.get(name.lower(), PROFILES["eco"])


def resolve_model(
    models_root: Path,
    profile_name: str,
    locale: str = "es",
) -> tuple[SpeechModelSpec, Path]:
    profile = resolve_profile(profile_name)
    normalized = locale.casefold().split("-", 1)[0]
    if normalized == "es" or normalized not in LOCALE_MODEL_PREFIX:
        spec = MODELS[profile.model_id]
        return spec, models_root / spec.directory
    prefix = LOCALE_MODEL_PREFIX[normalized]
    installed = sorted(
        path for path in models_root.glob(f"vosk-model-small-{prefix}*")
        if path.is_dir()
    )
    directory = installed[0].name if installed else f"vosk-model-small-{prefix}"
    spec = SpeechModelSpec(
        id=f"vosk-small-{normalized}",
        provider="vosk",
        languages=(normalized,),
        directory=directory,
    )
    return spec, models_root / directory
