"""Lightweight, deterministic interpretation of imperfect text and STT input."""

from .repair import Confidence, InterpretedIntent, NaturalLanguageRepair
from .intent_guard import (
    has_explicit_media_context, has_unnegated, is_ambiguous_media_play_verb,
    is_current_information_request, is_product_help_request,
)
from .negation import CommandConfidence, NegationResolution, NegationScopeResolver
from .writing import QualityProfile, WritingStyle, WritingStyleEngine, WritingStyleProfile
from .temporal import TemporalField, TemporalQueryResolver, TemporalResolution
from .spatial import LocationMemoryResolution, LocationMemoryResolver

__all__ = [
    "CommandConfidence", "Confidence", "InterpretedIntent", "NaturalLanguageRepair",
    "NegationResolution", "NegationScopeResolver", "QualityProfile",
    "WritingStyle", "WritingStyleEngine", "WritingStyleProfile",
    "TemporalField", "TemporalQueryResolver", "TemporalResolution",
    "LocationMemoryResolution", "LocationMemoryResolver",
    "has_explicit_media_context", "has_unnegated", "is_ambiguous_media_play_verb",
    "is_current_information_request", "is_product_help_request",
]
