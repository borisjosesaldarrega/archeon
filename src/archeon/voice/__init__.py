"""On-demand local voice pipeline."""

from .context import SpeechContextResolver, SpeechContextResult, SpeechTarget
from .pipeline import VoicePipeline
from .providers import SpeechToTextProvider, TextToSpeechProvider
from .speaker import SpeakerVerificationManager, cosine_similarity, speaker_embedding

__all__ = [
    "SpeechContextResolver", "SpeechContextResult", "SpeechTarget",
    "SpeechToTextProvider", "TextToSpeechProvider", "VoicePipeline",
    "SpeakerVerificationManager", "cosine_similarity", "speaker_embedding",
]
