"""Versioned, atomic, non-secret local configuration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from .lifecycle import ManagedComponent


@dataclass(slots=True)
class PerformanceConfig:
    profile: str = "balanced"
    animation_fps: int = 60
    idle_animation: bool = False


@dataclass(slots=True)
class GhostConfig:
    enabled: bool = False
    always_on_top: bool = True
    click_through: bool = False
    size: int = 112
    opacity: float = 1.0
    position_x: int | None = None
    position_y: int | None = None


@dataclass(slots=True)
class AudioConfig:
    enabled: bool = False
    backend: str = "wasapi_shared"
    input_device_id: str | None = None
    output_device_id: str | None = None


@dataclass(slots=True)
class VoiceConfig:
    profile: str = "eco"
    tts_voice_id: str | None = None
    tts_output_device_id: str | None = None
    tts_rate: int = 0
    tts_volume: int = 100
    barge_in: bool = True


SUPPORTED_LOCALES = ("es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi")


@dataclass(slots=True)
class LanguageConfig:
    interface: str = "es"
    conversation: str = "auto"
    input_mode: str = "auto"
    speech_recognition: str = "auto"
    speech_synthesis: str = "auto"
    regional_format: str = "system"


@dataclass(slots=True)
class AppearanceConfig:
    theme: str = "dark"
    background_type: str = "default"
    background_path: str | None = None
    background_fit: str = "cover"
    background_blur: int = 0
    background_opacity: int = 100
    logo_path: str | None = None
    reduced_motion: bool = False
    high_contrast: bool = False
    ui_scale: int = 100
    text_scale: int = 100


@dataclass(slots=True)
class AssistantConfig:
    wake_name: str = "Archeon"
    activation_mode: str = "push_to_talk"
    response_mode: str = "voice_and_text"
    wake_word_enabled: bool = False
    context_language_enabled: bool = True


@dataclass(slots=True)
class ClockConfig:
    visible: bool = True
    use_24_hour: bool = False
    show_seconds: bool = False
    show_date: bool = True


@dataclass(slots=True)
class PrivacyConfig:
    cloud_processing_allowed: bool = False
    cloud_screenshots_allowed: bool = False
    diagnostics_opt_in: bool = False
    save_history: bool = True


@dataclass(slots=True)
class StartupConfig:
    launch_at_login: bool = False
    start_minimized: bool = False
    start_in_ghost_mode: bool = False
    startup_sound: bool = False


@dataclass(slots=True)
class SyncConfig:
    enabled: bool = False
    settings: bool = True
    personalization: bool = True
    history: bool = False
    version: int = 0
    updated_at: str | None = None


@dataclass(slots=True)
class AppConfig:
    schema_version: int = 2
    locale: str = "es"
    theme: str = "dark"
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    ghost: GhostConfig = field(default_factory=GhostConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    language: LanguageConfig = field(default_factory=LanguageConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    clock: ClockConfig = field(default_factory=ClockConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    permissions: dict[str, str] = field(default_factory=dict)


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(base) / "ARCHEON" if base else Path.home() / ".archeon"


class ConfigurationManager(ManagedComponent):
    def __init__(self, path: Path | None = None) -> None:
        super().__init__("configuration")
        self.path = path or default_data_dir() / "config.json"
        self._config = AppConfig()
        self._lock = RLock()

    @property
    def config(self) -> AppConfig:
        return self._config

    def _start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._config = self._decode(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.save()

    def _stop(self) -> None:
        self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(asdict(self._config), ensure_ascii=False, indent=2)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix="config-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_path = Path(temporary.name)
            os.replace(temp_path, self.path)

    def set_permission(self, permission: str, state: str) -> None:
        with self._lock:
            self._config.permissions[permission] = state
            self.save()

    def public_settings(self) -> dict[str, Any]:
        """Return settings that are safe to expose to the loopback UI."""
        value = asdict(self._config)
        value.pop("permissions", None)
        return value

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Validate and atomically apply user-facing setting sections."""
        allowed = {
            "performance", "ghost", "audio", "voice", "language", "appearance",
            "assistant", "clock", "privacy", "startup", "sync",
        }
        current = asdict(self._config)
        for section_name, section_changes in changes.items():
            if section_name not in allowed or not isinstance(section_changes, dict):
                raise ValueError(f"invalid_settings_section:{section_name}")
            known = current.get(section_name)
            if not isinstance(known, dict):
                raise ValueError(f"invalid_settings_section:{section_name}")
            unknown = set(section_changes) - set(known)
            if unknown:
                raise ValueError(f"unknown_setting:{section_name}.{sorted(unknown)[0]}")
            known.update(section_changes)
        sync = current["sync"]
        sync["version"] = max(0, int(sync.get("version", 0))) + 1
        sync["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated = self._decode(current)
        with self._lock:
            self._config = updated
            self.save()
        return self.public_settings()

    def sync_payloads(self) -> dict[str, dict[str, Any]]:
        """Split portable account preferences from machine-specific settings."""
        value = self.public_settings()
        appearance = value["appearance"]
        account_appearance = {
            key: appearance[key]
            for key in ("theme", "reduced_motion", "high_contrast", "ui_scale", "text_scale")
        }
        device_appearance = {
            key: appearance[key]
            for key in (
                "background_type", "background_path", "background_fit", "background_blur",
                "background_opacity", "logo_path",
            )
        }
        envelope = {"version": value["sync"]["version"], "updated_at": value["sync"]["updated_at"]}
        return {
            "account": {
                **envelope,
                "settings": {
                    "language": value["language"],
                    "assistant": value["assistant"],
                    "appearance": account_appearance,
                    "privacy": value["privacy"],
                },
            },
            "device": {
                **envelope,
                "settings": {
                    "performance": value["performance"],
                    "ghost": value["ghost"],
                    "audio": value["audio"],
                    "voice": value["voice"],
                    "appearance": device_appearance,
                    "clock": value["clock"],
                    "startup": value["startup"],
                },
            },
        }

    @staticmethod
    def _decode(data: dict[str, Any]) -> AppConfig:
        def section(name: str) -> dict[str, Any]:
            value = data.get(name, {})
            return value if isinstance(value, dict) else {}

        def choice(value: Any, allowed: set[str], default: str) -> str:
            candidate = str(value).lower()
            return candidate if candidate in allowed else default

        language = section("language")
        appearance = section("appearance")
        assistant = section("assistant")
        clock = section("clock")
        privacy = section("privacy")
        startup = section("startup")
        sync = section("sync")
        profile = str(data.get("performance", {}).get("profile", "balanced")).lower()
        if profile not in {"eco", "balanced", "performance"}:
            profile = "balanced"
        fps_default = 30 if profile == "eco" else 60
        fps = int(data.get("performance", {}).get("animation_fps", fps_default))
        ghost_size = max(64, min(256, int(data.get("ghost", {}).get("size", 112))))
        opacity = max(0.2, min(1.0, float(data.get("ghost", {}).get("opacity", 1.0))))
        legacy_locale = choice(data.get("locale", "es"), set(SUPPORTED_LOCALES), "es")
        interface_locale = choice(language.get("interface", legacy_locale), set(SUPPORTED_LOCALES), legacy_locale)
        legacy_theme = choice(data.get("theme", "dark"), {"light", "dark", "system"}, "dark")
        selected_theme = choice(appearance.get("theme", legacy_theme), {"light", "dark", "system"}, legacy_theme)
        return AppConfig(
            schema_version=2,
            locale=interface_locale,
            theme=selected_theme,
            performance=PerformanceConfig(
                profile=profile,
                animation_fps=max(1, min(60, fps)),
                idle_animation=bool(data.get("performance", {}).get("idle_animation", False)),
            ),
            ghost=GhostConfig(
                enabled=bool(data.get("ghost", {}).get("enabled", False)),
                always_on_top=bool(data.get("ghost", {}).get("always_on_top", True)),
                click_through=bool(data.get("ghost", {}).get("click_through", False)),
                size=ghost_size,
                opacity=opacity,
                position_x=data.get("ghost", {}).get("position_x"),
                position_y=data.get("ghost", {}).get("position_y"),
            ),
            audio=AudioConfig(
                enabled=bool(data.get("audio", {}).get("enabled", False)),
                backend=str(data.get("audio", {}).get("backend", "wasapi_shared")),
                input_device_id=data.get("audio", {}).get("input_device_id"),
                output_device_id=data.get("audio", {}).get("output_device_id"),
            ),
            voice=VoiceConfig(
                profile=(
                    str(data.get("voice", {}).get("profile", "eco")).lower()
                    if str(data.get("voice", {}).get("profile", "eco")).lower()
                    in {"eco", "balanced", "performance"}
                    else "eco"
                ),
                tts_voice_id=data.get("voice", {}).get("tts_voice_id"),
                tts_output_device_id=data.get("voice", {}).get("tts_output_device_id"),
                tts_rate=max(-10, min(10, int(data.get("voice", {}).get("tts_rate", 0)))),
                tts_volume=max(0, min(100, int(data.get("voice", {}).get("tts_volume", 100)))),
                barge_in=bool(data.get("voice", {}).get("barge_in", True)),
            ),
            language=LanguageConfig(
                interface=interface_locale,
                conversation=choice(language.get("conversation", "auto"), set(SUPPORTED_LOCALES) | {"auto"}, "auto"),
                input_mode=choice(language.get("input_mode", "auto"), {"auto", "text", "voice"}, "auto"),
                speech_recognition=choice(language.get("speech_recognition", "auto"), set(SUPPORTED_LOCALES) | {"auto"}, "auto"),
                speech_synthesis=choice(language.get("speech_synthesis", "auto"), set(SUPPORTED_LOCALES) | {"auto"}, "auto"),
                regional_format=str(language.get("regional_format", "system"))[:32],
            ),
            appearance=AppearanceConfig(
                theme=selected_theme,
                background_type=choice(appearance.get("background_type", "default"), {"default", "image", "video"}, "default"),
                background_path=appearance.get("background_path"),
                background_fit=choice(appearance.get("background_fit", "cover"), {"cover", "contain", "stretch"}, "cover"),
                background_blur=max(0, min(40, int(appearance.get("background_blur", 0)))),
                background_opacity=max(0, min(100, int(appearance.get("background_opacity", 100)))),
                logo_path=appearance.get("logo_path"),
                reduced_motion=bool(appearance.get("reduced_motion", False)),
                high_contrast=bool(appearance.get("high_contrast", False)),
                ui_scale=max(75, min(150, int(appearance.get("ui_scale", 100)))),
                text_scale=max(75, min(200, int(appearance.get("text_scale", 100)))),
            ),
            assistant=AssistantConfig(
                wake_name=str(assistant.get("wake_name", "Archeon")).strip()[:24] or "Archeon",
                activation_mode=choice(assistant.get("activation_mode", "push_to_talk"), {"push_to_talk", "wake_word", "manual"}, "push_to_talk"),
                response_mode=choice(assistant.get("response_mode", "voice_and_text"), {"voice_and_text", "voice", "text"}, "voice_and_text"),
                wake_word_enabled=bool(assistant.get("wake_word_enabled", False)),
                context_language_enabled=bool(assistant.get("context_language_enabled", True)),
            ),
            clock=ClockConfig(
                visible=bool(clock.get("visible", True)),
                use_24_hour=bool(clock.get("use_24_hour", False)),
                show_seconds=bool(clock.get("show_seconds", False)),
                show_date=bool(clock.get("show_date", True)),
            ),
            privacy=PrivacyConfig(
                cloud_processing_allowed=bool(privacy.get("cloud_processing_allowed", False)),
                cloud_screenshots_allowed=bool(privacy.get("cloud_screenshots_allowed", False)),
                diagnostics_opt_in=bool(privacy.get("diagnostics_opt_in", False)),
                save_history=bool(privacy.get("save_history", True)),
            ),
            startup=StartupConfig(
                launch_at_login=bool(startup.get("launch_at_login", False)),
                start_minimized=bool(startup.get("start_minimized", False)),
                start_in_ghost_mode=bool(startup.get("start_in_ghost_mode", False)),
                startup_sound=bool(startup.get("startup_sound", False)),
            ),
            sync=SyncConfig(
                enabled=bool(sync.get("enabled", False)),
                settings=bool(sync.get("settings", True)),
                personalization=bool(sync.get("personalization", True)),
                history=bool(sync.get("history", False)),
                version=max(0, int(sync.get("version", 0))),
                updated_at=sync.get("updated_at"),
            ),
            permissions={str(key): str(value) for key, value in data.get("permissions", {}).items()},
        )
