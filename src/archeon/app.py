"""Composition root for the lightweight ARCHEON application."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from threading import RLock
from typing import Any

from archeon.audio import AudioManager
from archeon.auth import AuthManager, SupabaseAuthProvider, WindowsDpapiSessionVault
from archeon.core.config import ConfigurationManager, default_data_dir
from archeon.core.events import EventBus
from archeon.core.lifecycle import LifecycleManager
from archeon.core.orchestrator import Orchestrator
from archeon.core.permissions import PermissionEngine, RiskLevel
from archeon.core.secure_logging import close_logger, configure_logging, log_event
from archeon.core.tools import ToolEngine
from archeon.database import DatabaseManager
from archeon.media import MediaEngine, MediaState
from archeon.media.discovery import MediaDiscovery
from archeon.search import BraveSearchProvider, SearchEngine
from archeon.launcher import LauncherEngine
from archeon.plugins import PluginManager
from archeon.system import DeviceSystemEngine
from archeon.sync import SupabaseSettingsSync
from archeon.ui.server import UIServer
from archeon.voice import VoicePipeline


class ArcheonApplication:
    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        port: int = 0,
        console_log: bool = False,
        auth_provider: Any | None = None,
        auth_vault: Any | None = None,
    ) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.logger = configure_logging(self.data_dir / "logs", console=console_log)
        self.events = EventBus()
        self.configuration = ConfigurationManager(self.data_dir / "config.json")
        self.permissions = PermissionEngine(self.configuration)
        self.tools = ToolEngine(self.events, self.permissions)
        self.database = DatabaseManager()
        supabase_url = os.environ.get("ARCHEON_SUPABASE_URL", "https://rcgipowzivogyqbuwzlv.supabase.co")
        supabase_key = os.environ.get(
            "ARCHEON_SUPABASE_PUBLISHABLE_KEY",
            "sb_publishable_V0kfZlDv6HKNudCl_vObeQ_pRbDU1RU",
        )
        self.auth = AuthManager(
            self.events,
            auth_provider
            or SupabaseAuthProvider(
                supabase_url,
                supabase_key,
            ),
            auth_vault or WindowsDpapiSessionVault(self.data_dir / "secure" / "auth-session.dpapi"),
        )
        self.audio = AudioManager(self.events)
        self.media = MediaEngine(
            self.events,
            self.data_dir,
            output_device_provider=lambda: self.configuration.config.audio.output_device_id,
        )
        self.media_discovery = MediaDiscovery(
            self.data_dir,
            jamendo_client_id=os.environ.get("ARCHEON_JAMENDO_CLIENT_ID"),
        )
        self.search = SearchEngine(BraveSearchProvider(os.environ.get("ARCHEON_BRAVE_SEARCH_API_KEY")))
        self.launcher = LauncherEngine(self.data_dir)
        self.settings_sync = SupabaseSettingsSync(supabase_url, supabase_key, self.data_dir)
        self.plugins = PluginManager(self.events, self.data_dir / "plugins")
        self.system = DeviceSystemEngine(self.tools)
        self.orchestrator = Orchestrator(
            self.events,
            self.tools,
            conversation_language_provider=lambda: self.configuration.config.language.conversation,
            interface_language_provider=lambda: self.configuration.config.language.interface,
        )
        installation_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        models_root = Path(os.environ.get("ARCHEON_MODELS_DIR", installation_root / "models"))
        self.voice = VoicePipeline(
            self.events,
            self.audio,
            self.handle_command,
            models_root,
            input_device_provider=lambda: self.configuration.config.audio.input_device_id,
            locale_provider=self._speech_synthesis_locale,
            recognition_locale_provider=self._speech_recognition_locale,
            profile_provider=lambda: self.configuration.config.voice.profile,
            tts_config_provider=lambda: {
                "voice_id": self.configuration.config.voice.tts_voice_id,
                "output_device_id": self.configuration.config.voice.tts_output_device_id,
                "rate": self.configuration.config.voice.tts_rate,
                "volume": self.configuration.config.voice.tts_volume,
            },
            barge_in_provider=lambda: self.configuration.config.voice.barge_in,
            wake_enabled_provider=lambda: self.configuration.config.assistant.wake_word_enabled,
            wake_name_provider=lambda: self.configuration.config.assistant.wake_name,
        )
        self.ui_server = UIServer(
            self.events,
            command_handler=self.handle_command,
            action_handler=self.handle_action,
            health_handler=self.health,
            auth_handler=self.handle_auth,
            session_handler=self.handle_session,
            media_resource_handler=self.media.artwork,
            personalization_resource_handler=self._personalization_resource,
            port=port,
        )
        self.lifecycle = LifecycleManager(
            (
                self.configuration,
                self.database,
                self.auth,
                self.system,
                self.tools,
                self.audio,
                self.media,
                self.launcher,
                self.voice,
                self.plugins,
                self.ui_server,
            )
        )
        self._started = False
        self._lock = RLock()
        self.startup_ms = 0.0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            started = time.perf_counter()
            self.lifecycle.start()
            self._started = True
            self.startup_ms = (time.perf_counter() - started) * 1000
            self.events.publish(
                "app.started",
                {"startup_ms": round(self.startup_ms, 3)},
                source="application",
            )
            log_event(self.logger, "app.started", startup_ms=round(self.startup_ms, 3))

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self.events.publish("app.stopping", source="application")
            self.lifecycle.stop(suppress_errors=True)
            self.events.close()
            self._started = False
            log_event(self.logger, "app.stopped")
            close_logger(self.logger)

    def handle_command(self, text: str) -> dict[str, Any]:
        media_match = re.match(
            r"^(?:archeon[\s,]+)?(?:pon(?:me)?|reproduce|toca|play)\s+(?:la\s+canci[oó]n\s+)?(.+?)\s*[.!?]*$",
            text.strip(),
            flags=re.IGNORECASE,
        )
        if media_match:
            found = self.handle_action("media.search", {"query": media_match.group(1), "online": True, "limit": 1})
            results = found.get("results") if found.get("ok") else None
            if not results:
                error = found.get("error") or "media_not_found"
                return {"ok": False, "message": str(error), "data": found, "correlation_id": None}
            played = self.handle_action("media.play_result", {"id": results[0]["id"]})
            return {
                "ok": bool(played.get("ok")),
                "message": f"Reproduciendo {results[0]['title']}" if played.get("ok") else str(played.get("error")),
                "data": played,
                "correlation_id": None,
            }
        launch_item = self.launcher.command_item(text)
        if launch_item is not None:
            try:
                result = self.launcher.launch(launch_item.id)
                return {"ok": True, "message": f"Abriendo {launch_item.name}", "data": result, "correlation_id": None}
            except (OSError, ValueError) as error:
                return {"ok": False, "message": str(error), "data": {}, "correlation_id": None}
        response = self.orchestrator.handle_text(text)
        return {
            "ok": response.ok,
            "message": response.message,
            "data": response.data,
            "correlation_id": response.correlation_id,
        }

    def handle_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if action == "settings.get":
            return {"ok": True, "settings": self.configuration.public_settings()}
        if action == "settings.update":
            changes = payload.get("changes")
            if not isinstance(changes, dict):
                return {"ok": False, "error": "invalid_settings_changes"}
            try:
                settings = self.configuration.update_settings(changes)
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
            self.events.publish(
                "settings.changed",
                {"sections": sorted(changes)},
                source="application",
            )
            self.voice.sync_wake_word()
            return {"ok": True, "settings": settings}
        if action == "sync.now":
            try:
                identity, access_token = self.auth.cloud_identity(str(payload.get("_session_token", "")))
                envelopes = self.configuration.sync_payloads()
                envelopes["account"]["settings"]["launcher"] = self.launcher.portable_state()
                result = self.settings_sync.synchronize(
                    identity.user_id, access_token, envelopes["account"], envelopes["device"],
                )
                if not result.get("queued"):
                    settings = self.configuration.apply_sync_payloads(result["account"], result["device"])
                    launcher = result["account"].get("settings", {}).get("launcher")
                    if isinstance(launcher, dict):
                        self.launcher.apply_portable_state(launcher)
                    self.voice.sync_wake_word()
                    result["settings"] = settings
                self.events.publish(
                    "sync.completed" if not result.get("queued") else "sync.queued",
                    {"status": result.get("status")}, source="application",
                )
                return result
            except (OSError, TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "window.ghost":
            self.configuration.config.ghost.enabled = True
            self.configuration.save()
            self.events.publish("ui.window.ghost", source="application")
            return {"ok": True, "mode": "ghost"}
        if action == "window.main":
            self.configuration.config.ghost.enabled = False
            self.configuration.save()
            self.events.publish("ui.window.main", source="application")
            return {"ok": True, "mode": "main"}
        if action == "app.exit":
            self.events.publish("ui.window.exit", source="application")
            return {"ok": True}
        if action == "launcher.list":
            self.launcher.refresh(force=bool(payload.get("force")))
            return {"ok": True, "items": self.launcher.list_items(str(payload.get("category", "all")))}
        if action == "launcher.open":
            try:
                return {"ok": True, "item": self.launcher.launch(str(payload.get("id", "")))}
            except (OSError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "launcher.favorite":
            try:
                self.launcher.favorite(str(payload.get("id", "")), bool(payload.get("enabled")))
                self.configuration.touch_sync()
                return {"ok": True}
            except ValueError as error:
                return {"ok": False, "error": str(error)}
        if action == "media.index":
            decision = self.permissions.evaluate(
                ("filesystem.read.media",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Crear o actualizar el índice local de música en ubicaciones conocidas.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            roots = payload.get("roots")
            if roots is not None and (not isinstance(roots, list) or not all(isinstance(root, str) for root in roots)):
                return {"ok": False, "error": "invalid_media_roots"}
            try:
                return {"ok": True, "index": self.media_discovery.refresh([Path(root) for root in roots] if roots else None)}
            except OSError as error:
                return {"ok": False, "error": str(error)}
        if action == "media.search":
            query = str(payload.get("query", ""))
            limit = max(1, min(20, int(payload.get("limit", 10))))
            quality = str(payload.get("quality", "auto"))
            try:
                result = self.media_discovery.search(query, allow_online=False, limit=limit, quality=quality)
                if result["results"] or not bool(payload.get("online")):
                    return {"ok": True, **result}
                decision = self.permissions.evaluate(
                    ("network.media",), risk=RiskLevel.READ_ONLY, action=action,
                    reason="Buscar la canción solicitada en un proveedor online configurado.",
                    confirmer=lambda _request: True,
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.reason, **result}
                return {"ok": True, **self.media_discovery.search(query, allow_online=True, limit=limit, quality=quality)}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error), "results": []}
        if action == "media.play_result":
            try:
                result = self.media_discovery.resolve(str(payload.get("id", "")))
                self.media.load_results([result])
                return {"ok": True, "media": self.media.play()}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "search.web":
            decision = self.permissions.evaluate(
                ("network.search",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Consultar información actual y conservar las fuentes temporales.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            try:
                results = self.search.search(
                    str(payload.get("query", "")), limit=max(1, min(10, int(payload.get("limit", 5)))),
                    language=str(payload.get("language") or self.configuration.config.language.interface),
                    freshness=str(payload["freshness"]) if payload.get("freshness") else None,
                )
                return {"ok": True, "provider": self.search.provider.name, "results": results}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error), "results": []}
        if action == "launcher.alias":
            try:
                self.launcher.set_alias(str(payload.get("alias", "")), str(payload.get("id", "")))
                self.configuration.touch_sync()
                return {"ok": True}
            except ValueError as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.listen":
            decision = self.permissions.evaluate(
                ("microphone.capture",),
                risk=RiskLevel.MEDIUM,
                action="voice.listen",
                reason="Capturar una frase local para reconocer el comando de voz.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            if self.media.state is MediaState.PLAYING:
                self.media.pause()
            started = self.voice.start_cycle()
            return {"ok": started, "error": None if started else "voice_unavailable_or_busy"}
        if action == "voice.stop":
            self.voice.interrupt()
            return {"ok": True}
        if action == "voice.preview":
            try:
                started = self.voice.preview(str(payload.get("text", "")))
                return {"ok": started, "error": None if started else "voice_busy"}
            except (ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.catalog":
            try:
                catalog = self.voice.catalog()
                catalog["configuration"] = {
                    "profile": self.configuration.config.voice.profile,
                    "input_device_id": self.configuration.config.audio.input_device_id,
                    "tts_voice_id": self.configuration.config.voice.tts_voice_id,
                    "tts_output_device_id": self.configuration.config.voice.tts_output_device_id,
                    "tts_rate": self.configuration.config.voice.tts_rate,
                    "tts_volume": self.configuration.config.voice.tts_volume,
                    "barge_in": self.configuration.config.voice.barge_in,
                }
                return {"ok": True, "voice": catalog}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.configure":
            try:
                if self.voice.busy:
                    raise RuntimeError("voice_busy")
                catalog = self.voice.catalog()
                profile = str(payload.get("profile", "eco")).lower()
                if profile not in catalog["profiles"]:
                    raise ValueError("invalid_voice_profile")
                input_id = payload.get("input_device_id") or None
                voice_id = payload.get("tts_voice_id") or None
                output_id = payload.get("tts_output_device_id") or None
                if input_id is not None and str(input_id) not in {
                    str(device.get("index")) for device in catalog["input_devices"]
                }:
                    raise ValueError("invalid_input_device")
                if voice_id is not None and voice_id not in {
                    voice["id"] for voice in catalog["tts_voices"]
                }:
                    raise ValueError("invalid_tts_voice")
                if output_id is not None and output_id not in {
                    output["id"] for output in catalog["tts_outputs"]
                }:
                    raise ValueError("invalid_tts_output")
                self.configuration.config.voice.profile = profile
                self.configuration.config.audio.input_device_id = str(input_id) if input_id is not None else None
                self.configuration.config.voice.tts_voice_id = voice_id
                self.configuration.config.voice.tts_output_device_id = output_id
                self.configuration.config.voice.tts_rate = max(-10, min(10, int(payload.get("tts_rate", 0))))
                self.configuration.config.voice.tts_volume = max(0, min(100, int(payload.get("tts_volume", 100))))
                self.configuration.config.voice.barge_in = bool(payload.get("barge_in", True))
                self.configuration.save()
                self.events.publish("voice.configuration.changed", source="application")
                return {"ok": True, "voice": self.voice.status()}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        try:
            if action == "appearance.choose":
                from archeon.ui.native_dialogs import choose_visual_file

                kind = str(payload.get("kind", ""))
                selected = choose_visual_file(kind)
                if not selected:
                    return {"ok": True, "cancelled": True}
                path = Path(selected)
                max_bytes = 2_000_000_000 if kind == "video" else 50_000_000
                allowed = {"image": {".png", ".jpg", ".jpeg", ".webp", ".bmp"}, "video": {".mp4", ".webm", ".m4v"}, "logo": {".png", ".jpg", ".jpeg", ".webp"}}
                if kind not in allowed or path.suffix.casefold() not in allowed[kind] or not path.is_file() or path.stat().st_size > max_bytes:
                    return {"ok": False, "error": "invalid_visual_file"}
                changes = {"appearance": {"logo_path": str(path)}} if kind == "logo" else {"appearance": {"background_type": kind, "background_path": str(path)}}
                settings = self.configuration.update_settings(changes)
                self.events.publish("appearance.changed", {"kind": kind}, source="application")
                return {"ok": True, "settings": settings}
            if action == "appearance.clear":
                settings = self.configuration.update_settings({"appearance": {"background_type": "default", "background_path": None, "logo_path": None}})
                self.events.publish("appearance.changed", {"kind": "default"}, source="application")
                return {"ok": True, "settings": settings}
            if action == "media.load":
                paths = payload.get("paths")
                if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                    return {"ok": False, "error": "invalid_media_paths"}
                decision = self.permissions.evaluate(
                    ("filesystem.read.media",),
                    risk=RiskLevel.READ_ONLY,
                    action="media.load",
                    reason="Leer metadata y reproducir los archivos seleccionados.",
                    confirmer=lambda _request: True,
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.reason}
                return {"ok": True, "tracks": self.media.load([Path(path) for path in paths], append=bool(payload.get("append")))}
            if action == "media.choose":
                from archeon.ui.native_dialogs import choose_audio_files

                paths = choose_audio_files()
                if not paths:
                    return {"ok": True, "cancelled": True, "tracks": []}
                return {"ok": True, "tracks": self.media.load([Path(path) for path in paths])}
            if action in {"media.play", "music.started"}:
                if self.media.current is None:
                    self.media.load([Path(__file__).resolve().parent / "ui" / "archeon-audio.mp3"])
                return {"ok": True, "media": self.media.play()}
            if action in {"media.pause", "music.paused"}:
                return {"ok": True, "media": self.media.pause()}
            if action == "media.resume":
                return {"ok": True, "media": self.media.resume()}
            if action in {"media.stop", "music.stopped"}:
                return {"ok": True, "media": self.media.stop_playback()}
            if action == "media.next":
                return {"ok": True, "media": self.media.next()}
            if action == "media.previous":
                return {"ok": True, "media": self.media.previous()}
            if action == "media.seek":
                return {"ok": True, "media": self.media.seek(int(payload.get("position_ms", 0)))}
            if action == "media.volume":
                return {"ok": True, "media": self.media.set_volume(float(payload.get("volume", 0.7)))}
        except (OSError, ValueError, RuntimeError) as error:
            return {"ok": False, "error": str(error)}
        return {"ok": False, "error": f"unknown action: {action}"}

    def _speech_synthesis_locale(self) -> str:
        selected = self.configuration.config.language.speech_synthesis
        if selected != "auto":
            return selected
        conversation = self.configuration.config.language.conversation
        return conversation if conversation != "auto" else self.configuration.config.language.interface

    def _speech_recognition_locale(self) -> str:
        selected = self.configuration.config.language.speech_recognition
        if selected != "auto":
            return selected
        conversation = self.configuration.config.language.conversation
        return conversation if conversation != "auto" else self.configuration.config.language.interface

    def _personalization_resource(self, kind: str) -> Path | None:
        configured = self.configuration.config.appearance
        candidate = configured.background_path if kind == "background" else configured.logo_path if kind == "logo" else None
        if not candidate:
            return None
        path = Path(candidate).expanduser()
        return path if path.is_file() else None

    def handle_auth(
        self, operation: str, payload: dict[str, Any], session_token: str
    ) -> dict[str, Any]:
        try:
            if operation == "guest":
                session = self.auth.guest()
            elif operation == "login":
                session = self.auth.login(str(payload.get("email", "")), str(payload.get("password", "")))
            elif operation == "register":
                session = self.auth.register(
                    str(payload.get("email", "")),
                    str(payload.get("password", "")),
                    str(payload.get("display_name", "")),
                )
            elif operation == "restore":
                session = self.auth.restore()
                if session is None:
                    return {"ok": False, "error": "session_unavailable"}
            elif operation == "refresh":
                session = self.auth.refresh(session_token)
            elif operation == "forgot-password":
                self.auth.forgot_password(str(payload.get("email", "")))
                return {"ok": True}
            elif operation == "reauthenticate":
                self.auth.reauthenticate(session_token)
                return {"ok": True}
            elif operation == "change-password":
                password = str(payload.get("password", ""))
                if len(password) < 10:
                    return {"ok": False, "error": "password_too_short"}
                session = self.auth.update_user(
                    session_token,
                    {"password": password, "nonce": str(payload.get("nonce", "")).strip()},
                )
            elif operation == "change-email":
                email = str(payload.get("email", "")).strip()
                if "@" not in email or len(email) > 254:
                    return {"ok": False, "error": "invalid_email"}
                session = self.auth.update_user(session_token, {"email": email})
            elif operation == "logout-others":
                return {"ok": self.auth.logout_others(session_token)}
            elif operation == "mfa-status":
                return {"ok": True, "factors": self.auth.mfa_status(session_token)}
            elif operation == "mfa-enroll":
                return {"ok": True, "factor": self.auth.mfa_enroll(session_token, str(payload.get("friendly_name", "")))}
            elif operation == "mfa-verify":
                session = self.auth.mfa_verify(session_token, str(payload.get("factor_id", "")), str(payload.get("code", "")))
            elif operation == "mfa-unenroll":
                self.auth.mfa_unenroll(session_token, str(payload.get("factor_id", "")))
                return {"ok": True}
            elif operation == "delete-account":
                if payload.get("confirmation") != "DELETE":
                    return {"ok": False, "error": "delete_confirmation_required"}
                self.voice.interrupt()
                self.permissions.clear_session()
                return {"ok": self.auth.delete_account(session_token)}
            elif operation == "logout":
                self.voice.interrupt()
                self.permissions.clear_session()
                return {"ok": self.auth.logout(session_token)}
            else:
                return {"ok": False, "error": "unknown_auth_operation"}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "session_token": session.token, "session": session.public()}

    def handle_session(self, session_token: str) -> dict[str, Any]:
        session = self.auth.get(session_token)
        return {"ok": session is not None, "session": session.public() if session else None}

    def health(self) -> dict[str, Any]:
        return {
            "ok": self._started,
            "startup_ms": round(self.startup_ms, 3),
            "tools_registered": len(self.tools.manifests()),
            "tools_loaded": self.tools.loaded_tool_count,
            "database": self.database.health(),
            "audio_backend_loaded": self.audio.backend_loaded,
            "plugins_loaded": self.plugins.loaded_count,
            "launcher_loaded": self.launcher.loaded,
            "auth_provider": self.auth.provider_name,
            "voice": self.voice.status(),
            "media": self.media.status(),
            "event_subscribers": self.events.subscriber_count,
        }

    def __enter__(self) -> ArcheonApplication:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
