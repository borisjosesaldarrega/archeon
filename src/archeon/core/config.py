"""Versioned, atomic, non-secret local configuration."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from .lifecycle import ManagedComponent
from .paths import AppPaths


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
    tts_style: str = "natural"
    tts_voice_id: str | None = None
    tts_output_device_id: str | None = None
    tts_rate: int = 0
    tts_volume: int = 100
    barge_in: bool = True
    speaker_verification_enabled: bool = False
    speaker_rejection_feedback: str = "silent"


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
    accent_color: str = "#00F3FF"
    background_type: str = "default"
    background_path: str | None = None
    background_fit: str = "cover"
    background_blur: int = 0
    background_opacity: int = 100
    background_position_x: float = 0.0
    background_position_y: float = 0.0
    background_zoom: int = 100
    logo_path: str | None = None
    logo_position_x: float = 0.0
    logo_position_y: float = 0.0
    logo_zoom: int = 100
    logo_visible: bool = True
    chat_background_path: str | None = None
    reduced_motion: bool = False
    high_contrast: bool = False
    large_targets: bool = False
    left_handed: bool = False
    visual_voice_cues: bool = True
    ui_scale: int = 100
    text_scale: int = 100
    command_input_visible: bool = True
    status_indicator_visible: bool = True
    interface_layout: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class AssistantConfig:
    wake_name: str = "Archeon"
    preferred_name: str = ""
    activation_mode: str = "push_to_talk"
    response_mode: str = "voice_and_text"
    wake_word_enabled: bool = False
    context_language_enabled: bool = True
    listening_paused: bool = False
    pause_listening_phrase: str = "deja de escuchar"
    resume_listening_phrase: str = "vuelve a escuchar"


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
class ApprovalConfig:
    """Local authorization posture for actions that still have no explicit grant."""

    mode: str = "ask"


@dataclass(slots=True)
class ComputerUseConfig:
    action_display: str = "normal"


@dataclass(slots=True)
class StartupConfig:
    launch_at_login: bool = False
    start_minimized: bool = False
    start_in_ghost_mode: bool = False
    startup_sound: bool = False
    window_mode: str = "normal"


@dataclass(slots=True)
class SyncConfig:
    enabled: bool = False
    settings: bool = True
    personalization: bool = True
    history: bool = False
    version: int = 0
    updated_at: str | None = None


@dataclass(slots=True)
class StorageConfig:
    model_dir: str | None = None


@dataclass(slots=True)
class IntelligenceConfig:
    enabled: bool = True
    model_id: str = "qwen3-4b-q4-k-m"
    backend: str = "cpu"
    profile: str = "balanced"
    context_size: int = 4096
    max_tokens: int = 1024
    keep_warm_seconds: int = 30
    threads: int = 6
    cloud_fallback: bool = False
    memory_enabled: bool = True
    conversation_turns: int = 4


@dataclass(slots=True)
class PersonalityConfig:
    style: str = "natural"
    detail: int = 50
    proactivity: int = 50
    humor: int = 15
    formality: int = 45
    creativity: int = 35


@dataclass(slots=True)
class MediaConfig:
    alternative_versions: str = "ask"
    preferred_volume: int = 70
    dj_mode: bool = False
    autoplay: bool = False
    dj_strategy: str = "mixed"
    show_album_art: bool = True
    vinyl_orb: bool = True
    local_library: bool = True
    online_providers: bool = True
    notification_volume: int = 70


@dataclass(slots=True)
class AppConfig:
    schema_version: int = 5
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
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    computer_use: ComputerUseConfig = field(default_factory=ComputerUseConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    permissions: dict[str, str] = field(default_factory=dict)


def default_data_dir() -> Path:
    return AppPaths.discover().data_dir


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
            "assistant", "clock", "privacy", "startup", "sync", "storage",
            "intelligence", "personality", "media", "approval", "computer_use",
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

    def touch_sync(self) -> None:
        """Mark separately persisted portable state as newer for conflict resolution."""
        with self._lock:
            self._config.sync.version += 1
            self._config.sync.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def sync_payloads(self) -> dict[str, dict[str, Any]]:
        """Split portable account preferences from machine-specific settings."""
        value = self.public_settings()
        appearance = value["appearance"]
        account_appearance = {key: appearance[key] for key in (
            "theme", "accent_color", "background_fit", "background_blur", "background_opacity",
            "reduced_motion", "high_contrast", "ui_scale", "text_scale",
            "large_targets", "left_handed", "visual_voice_cues",
            "command_input_visible",
            "status_indicator_visible",
            "logo_visible",
        )}
        device_appearance = {
            key: appearance[key]
            for key in (
                "background_type", "background_path", "background_position_x",
                "background_position_y", "background_zoom", "logo_path",
                "logo_position_x", "logo_position_y", "logo_zoom",
                "chat_background_path",
                "interface_layout",
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
                    "clock": value["clock"],
                    "ghost": {
                        key: value["ghost"][key]
                        for key in ("enabled", "always_on_top", "click_through", "size", "opacity")
                    },
                    "voice": {
                        key: value["voice"][key]
                        for key in ("profile", "tts_style", "tts_rate", "tts_volume", "barge_in")
                    },
                    "privacy": value["privacy"],
                    "personality": value["personality"],
                    "media": value["media"],
                    "intelligence": {
                        key: value["intelligence"][key]
                        for key in ("profile", "memory_enabled", "conversation_turns")
                    },
                },
            },
            "device": {
                **envelope,
                "settings": {
                    "performance": value["performance"],
                    "ghost": {
                        "position_x": value["ghost"]["position_x"],
                        "position_y": value["ghost"]["position_y"],
                    },
                    "audio": value["audio"],
                    "voice": {
                        "tts_voice_id": value["voice"]["tts_voice_id"],
                        "tts_output_device_id": value["voice"]["tts_output_device_id"],
                        "speaker_verification_enabled": value["voice"]["speaker_verification_enabled"],
                        "speaker_rejection_feedback": value["voice"]["speaker_rejection_feedback"],
                    },
                    "appearance": device_appearance,
                    "startup": value["startup"],
                    "approval": value["approval"],
                },
            },
        }

    def apply_sync_payloads(self, account: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
        """Merge validated cloud envelopes while retaining unsynchronized local fields."""
        current = self.public_settings()
        for envelope in (account, device):
            settings = envelope.get("settings", {})
            if not isinstance(settings, dict):
                continue
            for section_name, section_value in settings.items():
                if section_name == "launcher" or not isinstance(section_value, dict):
                    continue
                section = current.get(section_name)
                if isinstance(section, dict):
                    section.update(section_value)
        versions = [max(0, int(item.get("version", 0))) for item in (account, device)]
        current["sync"]["version"] = max([current["sync"]["version"], *versions])
        timestamps = [str(item.get("updated_at")) for item in (account, device) if item.get("updated_at")]
        if timestamps:
            current["sync"]["updated_at"] = max(timestamps)
        updated = self._decode(current)
        with self._lock:
            self._config = updated
            self.save()
        return self.public_settings()

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
        approval = section("approval")
        computer_use = section("computer_use")
        startup = section("startup")
        sync = section("sync")
        storage = section("storage")
        intelligence = section("intelligence")
        personality = section("personality")
        media = section("media")
        raw_tts_style = str(data.get("voice", {}).get("tts_style", "natural")).lower()
        tts_style = {"deep_tech": "deep", "crisp": "technological"}.get(raw_tts_style, raw_tts_style)
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
        accent_color = str(appearance.get("accent_color", "#00F3FF")).upper()
        if re.fullmatch(r"#[0-9A-F]{6}", accent_color) is None:
            accent_color = "#00F3FF"
        raw_interface_layout = appearance.get("interface_layout", {})
        interface_layout: dict[str, dict[str, Any]] = {}
        essential_layout_items = {"menu_toggle"}
        allowed_layout_items = {
            "clock", "session_badge", "command_toggle", "ghost_toggle", "menu_toggle",
            "orb", "assistant_name", "assistant_detail", "voice_button",
            "conversation", "command", "music",
        }
        legacy_layout_groups = {
            "top_actions": ("session_badge", "command_toggle", "ghost_toggle", "menu_toggle"),
            "status": ("assistant_name", "assistant_detail", "voice_button"),
            "command": ("conversation", "command"),
        }
        if isinstance(raw_interface_layout, dict):
            raw_interface_layout = dict(raw_interface_layout)
            for legacy_name, replacement_names in legacy_layout_groups.items():
                legacy_value = raw_interface_layout.get(legacy_name)
                if not isinstance(legacy_value, dict):
                    continue
                for replacement_name in replacement_names:
                    raw_interface_layout.setdefault(replacement_name, legacy_value)
        if isinstance(raw_interface_layout, dict):
            for item_name, item_value in raw_interface_layout.items():
                if item_name not in allowed_layout_items or not isinstance(item_value, dict):
                    continue
                raw_color = str(item_value.get("color", "")).upper()
                raw_background = str(item_value.get("background", "")).upper()
                raw_text_color = str(item_value.get("text_color", "")).upper()
                raw_style = str(item_value.get("style", "card")).lower()
                interface_layout[item_name] = {
                    "x": max(-2000.0, min(2000.0, float(item_value.get("x", 0)))),
                    "y": max(-1200.0, min(1200.0, float(item_value.get("y", 0)))),
                    "color": raw_color if re.fullmatch(r"#[0-9A-F]{6}", raw_color) else None,
                    "background": raw_background if re.fullmatch(r"#[0-9A-F]{6}", raw_background) else None,
                    "text_color": raw_text_color if re.fullmatch(r"#[0-9A-F]{6}", raw_text_color) else None,
                    "style": raw_style if item_name == "conversation" and raw_style in {"card", "compact", "bubbles"} else "card",
                    "visible": True if item_name in essential_layout_items else bool(item_value.get("visible", True)),
                    "scale": max(50, min(180, int(item_value.get("scale", 100)))),
                    "width": max(35, min(100, int(item_value.get("width", 70)))),
                    "anchor": "viewport" if item_value.get("anchor") == "viewport" else "flow",
                    "left": max(0.0, min(100.0, float(item_value.get("left", 50)))),
                    "top": max(0.0, min(100.0, float(item_value.get("top", 50)))),
                }
        return AppConfig(
            schema_version=5,
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
                tts_style=choice(tts_style, {
                    "natural", "deep", "technological", "warm", "professional",
                    "energetic", "calm", "cinematic", "custom",
                }, "natural"),
                tts_voice_id=data.get("voice", {}).get("tts_voice_id"),
                tts_output_device_id=data.get("voice", {}).get("tts_output_device_id"),
                tts_rate=max(-10, min(10, int(data.get("voice", {}).get("tts_rate", 0)))),
                tts_volume=max(0, min(100, int(data.get("voice", {}).get("tts_volume", 100)))),
                barge_in=bool(data.get("voice", {}).get("barge_in", True)),
                speaker_verification_enabled=bool(data.get("voice", {}).get("speaker_verification_enabled", False)),
                speaker_rejection_feedback=choice(
                    data.get("voice", {}).get("speaker_rejection_feedback", "silent"),
                    {"silent", "visual"}, "silent",
                ),
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
                accent_color=accent_color,
                background_type=choice(appearance.get("background_type", "default"), {"default", "image", "video"}, "default"),
                background_path=appearance.get("background_path"),
                background_fit=choice(appearance.get("background_fit", "cover"), {"cover", "contain", "stretch"}, "cover"),
                background_blur=max(0, min(40, int(appearance.get("background_blur", 0)))),
                background_opacity=max(0, min(100, int(appearance.get("background_opacity", 100)))),
                background_position_x=max(-40.0, min(40.0, float(appearance.get("background_position_x", 0)))),
                background_position_y=max(-40.0, min(40.0, float(appearance.get("background_position_y", 0)))),
                background_zoom=max(100, min(250, int(appearance.get("background_zoom", 100)))),
                logo_path=appearance.get("logo_path"),
                logo_position_x=max(-40.0, min(40.0, float(appearance.get("logo_position_x", 0)))),
                logo_position_y=max(-40.0, min(40.0, float(appearance.get("logo_position_y", 0)))),
                logo_zoom=max(100, min(250, int(appearance.get("logo_zoom", 100)))),
                logo_visible=bool(appearance.get("logo_visible", True)),
                chat_background_path=appearance.get("chat_background_path"),
                reduced_motion=bool(appearance.get("reduced_motion", False)),
                high_contrast=bool(appearance.get("high_contrast", False)),
                large_targets=bool(appearance.get("large_targets", False)),
                left_handed=bool(appearance.get("left_handed", False)),
                visual_voice_cues=bool(appearance.get("visual_voice_cues", True)),
                ui_scale=max(75, min(150, int(appearance.get("ui_scale", 100)))),
                text_scale=max(75, min(200, int(appearance.get("text_scale", 100)))),
                command_input_visible=bool(appearance.get("command_input_visible", True)),
                status_indicator_visible=bool(appearance.get("status_indicator_visible", True)),
                interface_layout=interface_layout,
            ),
            assistant=AssistantConfig(
                wake_name=str(assistant.get("wake_name", "Archeon")).strip()[:24] or "Archeon",
                preferred_name=str(assistant.get("preferred_name", "")).strip()[:40],
                activation_mode=choice(assistant.get("activation_mode", "push_to_talk"), {"push_to_talk", "wake_word", "manual"}, "push_to_talk"),
                response_mode=choice(assistant.get("response_mode", "voice_and_text"), {"voice_and_text", "voice", "text"}, "voice_and_text"),
                wake_word_enabled=bool(assistant.get("wake_word_enabled", False)),
                context_language_enabled=bool(assistant.get("context_language_enabled", True)),
                listening_paused=bool(assistant.get("listening_paused", False)),
                pause_listening_phrase=str(assistant.get("pause_listening_phrase", "deja de escuchar")).strip()[:80] or "deja de escuchar",
                resume_listening_phrase=str(assistant.get("resume_listening_phrase", "vuelve a escuchar")).strip()[:80] or "vuelve a escuchar",
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
            approval=ApprovalConfig(
                mode=choice(
                    approval.get("mode", "ask"),
                    {"ask", "balanced", "full_control"},
                    "ask",
                ),
            ),
            computer_use=ComputerUseConfig(
                action_display=choice(
                    computer_use.get("action_display", "normal"),
                    {"normal", "visible", "fast"}, "normal",
                ),
            ),
            startup=StartupConfig(
                launch_at_login=bool(startup.get("launch_at_login", False)),
                start_minimized=bool(startup.get("start_minimized", False)),
                start_in_ghost_mode=bool(startup.get("start_in_ghost_mode", False)),
                startup_sound=bool(startup.get("startup_sound", False)),
                window_mode=choice(
                    startup.get(
                        "window_mode",
                        "minimized" if startup.get("start_minimized", False) else "normal",
                    ),
                    {"normal", "maximized", "minimized"},
                    "normal",
                ),
            ),
            sync=SyncConfig(
                enabled=bool(sync.get("enabled", False)),
                settings=bool(sync.get("settings", True)),
                personalization=bool(sync.get("personalization", True)),
                history=bool(sync.get("history", False)),
                version=max(0, int(sync.get("version", 0))),
                updated_at=sync.get("updated_at"),
            ),
            storage=StorageConfig(
                model_dir=str(storage.get("model_dir")).strip()[:1024]
                if storage.get("model_dir") else None,
            ),
            intelligence=IntelligenceConfig(
                enabled=bool(intelligence.get("enabled", True)),
                model_id=str(intelligence.get("model_id", "qwen3-4b-q4-k-m"))[:120],
                backend=choice(intelligence.get("backend", "cpu"), {"cpu", "vulkan", "auto"}, "cpu"),
                profile=choice(intelligence.get("profile", "balanced"), {"eco", "balanced", "performance"}, "balanced"),
                context_size=max(512, min(32768, int(intelligence.get("context_size", 4096)))),
                max_tokens=max(32, min(4096, int(intelligence.get("max_tokens", 1024)))),
                keep_warm_seconds=max(0, min(3600, int(intelligence.get("keep_warm_seconds", 30)))),
                threads=max(1, min(64, int(intelligence.get("threads", 6)))),
                cloud_fallback=bool(intelligence.get("cloud_fallback", False)),
                memory_enabled=bool(intelligence.get("memory_enabled", True)),
                conversation_turns=max(0, min(12, int(intelligence.get("conversation_turns", 4)))),
            ),
            personality=PersonalityConfig(
                style=choice(personality.get("style", "natural"), {"professional", "natural", "direct", "creative", "technical", "custom"}, "natural"),
                detail=max(0, min(100, int(personality.get("detail", 50)))),
                proactivity=max(0, min(100, int(personality.get("proactivity", 50)))),
                humor=max(0, min(100, int(personality.get("humor", 15)))),
                formality=max(0, min(100, int(personality.get("formality", 45)))),
                creativity=max(0, min(100, int(personality.get("creativity", 35)))),
            ),
            media=MediaConfig(
                alternative_versions=choice(
                    media.get("alternative_versions", "ask"),
                    {"ask", "automatic", "strict"}, "ask",
                ),
                preferred_volume=max(0, min(100, int(media.get("preferred_volume", 70)))),
                dj_mode=bool(media.get("dj_mode", False)),
                autoplay=bool(media.get("autoplay", False)),
                dj_strategy=choice(media.get("dj_strategy", "mixed"), {"same_artist", "similar_artist", "same_genre", "mixed"}, "mixed"),
                show_album_art=bool(media.get("show_album_art", True)),
                vinyl_orb=bool(media.get("vinyl_orb", True)),
                local_library=bool(media.get("local_library", True)),
                online_providers=bool(media.get("online_providers", True)),
                notification_volume=max(0, min(100, int(media.get("notification_volume", 70)))),
            ),
            permissions={str(key): str(value) for key, value in data.get("permissions", {}).items()},
        )
