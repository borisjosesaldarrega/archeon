"""Central voice model/profile catalog; model names are not spread through the app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
