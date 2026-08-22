"""On-demand local voice pipeline."""

from .pipeline import VoicePipeline
from .providers import SpeechToTextProvider, TextToSpeechProvider

__all__ = ["SpeechToTextProvider", "TextToSpeechProvider", "VoicePipeline"]
