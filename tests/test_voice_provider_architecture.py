from __future__ import annotations

import sys
from threading import Event
from types import ModuleType

from archeon.voice.catalog import VOICE_STYLES, resolve_voice_style
from archeon.voice.providers import (
    LocalNeuralVoiceProvider,
    SapiTextToSpeech,
    SpeechSynthesisMetrics,
    VoiceProvider,
    WindowsSapiProvider,
)


def test_voice_catalog_has_all_public_styles_and_safe_fallbacks() -> None:
    assert set(VOICE_STYLES) == {
        "natural",
        "deep",
        "technological",
        "warm",
        "professional",
        "energetic",
        "calm",
        "cinematic",
        "custom",
    }
    assert resolve_voice_style("deep_tech").id == "deep"
    assert resolve_voice_style("crisp").id == "technological"
    assert resolve_voice_style("unknown").id == "natural"
    assert resolve_voice_style("custom", ("natural", "calm")).id == "natural"


def test_sapi_compatibility_name_and_provider_contract() -> None:
    provider = WindowsSapiProvider()
    assert SapiTextToSpeech is WindowsSapiProvider
    assert isinstance(provider, VoiceProvider)
    assert provider.capabilities.local is True
    assert provider.capabilities.neural is False
    assert provider.capabilities.exposes_first_audio_timing is False
    assert "custom" not in provider.capabilities.styles
    assert hasattr(LocalNeuralVoiceProvider, "load")
    assert hasattr(LocalNeuralVoiceProvider, "unload")


class _FakeVoice:
    def __init__(self) -> None:
        self.Rate = 0
        self.Volume = 100
        self.spoken: list[tuple[str, int]] = []

    def GetVoices(self) -> list[object]:
        return []

    def Speak(self, text: str, flags: int) -> None:
        self.spoken.append((text, flags))

    def WaitUntilDone(self, _timeout: int) -> bool:
        return True


def test_sapi_returns_integrable_metrics_and_degrades_custom(monkeypatch) -> None:
    fake_voice = _FakeVoice()
    client = ModuleType("comtypes.client")
    client.CreateObject = lambda name: fake_voice  # type: ignore[attr-defined]
    comtypes = ModuleType("comtypes")
    comtypes.CoInitialize = lambda: None  # type: ignore[attr-defined]
    comtypes.CoUninitialize = lambda: None  # type: ignore[attr-defined]
    comtypes.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)

    provider = WindowsSapiProvider()
    metrics = provider.speak("Hola", Event(), style="custom")

    assert isinstance(metrics, SpeechSynthesisMetrics)
    assert metrics.requested_style == "custom"
    assert metrics.applied_style == "natural"
    assert metrics.dispatch_ms >= 0
    assert metrics.total_ms >= metrics.dispatch_ms
    assert metrics.first_audio_ms is None
    assert provider.last_metrics == metrics
    assert fake_voice.spoken == [("Hola", 1)]


def test_sapi_approximates_supported_style_without_extra_runtime(monkeypatch) -> None:
    fake_voice = _FakeVoice()
    client = ModuleType("comtypes.client")
    client.CreateObject = lambda name: fake_voice  # type: ignore[attr-defined]
    comtypes = ModuleType("comtypes")
    comtypes.CoInitialize = lambda: None  # type: ignore[attr-defined]
    comtypes.CoUninitialize = lambda: None  # type: ignore[attr-defined]
    comtypes.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)

    metrics = WindowsSapiProvider().speak("A & B", Event(), style="cinematic")

    assert metrics.applied_style == "cinematic"
    assert fake_voice.Rate == -2
    assert fake_voice.spoken == [('<pitch middle="-3">A &amp; B</pitch>', 9)]
