"""Composition root for the lightweight ARCHEON application."""

from __future__ import annotations

import time
from pathlib import Path
from threading import RLock
from typing import Any

from archeon.audio import AudioManager
from archeon.auth import AuthManager, DevelopmentAuthProvider
from archeon.core.config import ConfigurationManager, default_data_dir
from archeon.core.events import EventBus
from archeon.core.lifecycle import LifecycleManager
from archeon.core.orchestrator import Orchestrator
from archeon.core.permissions import PermissionEngine, RiskLevel
from archeon.core.secure_logging import close_logger, configure_logging, log_event
from archeon.core.tools import ToolEngine
from archeon.database import DatabaseManager
from archeon.media import MediaEngine, MediaState
from archeon.plugins import PluginManager
from archeon.system import DeviceSystemEngine
from archeon.ui.server import UIServer
from archeon.voice import VoicePipeline


class ArcheonApplication:
    def __init__(self, *, data_dir: Path | None = None, port: int = 0, console_log: bool = False) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.logger = configure_logging(self.data_dir / "logs", console=console_log)
        self.events = EventBus()
        self.configuration = ConfigurationManager(self.data_dir / "config.json")
        self.permissions = PermissionEngine(self.configuration)
        self.tools = ToolEngine(self.events, self.permissions)
        self.database = DatabaseManager()
        self.auth = AuthManager(
            self.events,
            DevelopmentAuthProvider(self.data_dir / "development-auth.json"),
        )
        self.audio = AudioManager(self.events)
        self.media = MediaEngine(
            self.events,
            self.data_dir,
            output_device_provider=lambda: self.configuration.config.audio.output_device_id,
        )
        self.plugins = PluginManager(self.events, self.data_dir / "plugins")
        self.system = DeviceSystemEngine(self.tools)
        self.orchestrator = Orchestrator(self.events, self.tools)
        model_path = Path(__file__).resolve().parents[2] / "models" / "vosk-model-small-es-0.42"
        self.voice = VoicePipeline(
            self.events,
            self.audio,
            self.handle_command,
            model_path,
            input_device_provider=lambda: self.configuration.config.audio.input_device_id,
            locale_provider=lambda: self.configuration.config.locale,
        )
        self.ui_server = UIServer(
            self.events,
            command_handler=self.handle_command,
            action_handler=self.handle_action,
            health_handler=self.health,
            auth_handler=self.handle_auth,
            session_handler=self.handle_session,
            media_resource_handler=self.media.artwork,
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
        response = self.orchestrator.handle_text(text)
        return {
            "ok": response.ok,
            "message": response.message,
            "data": response.data,
            "correlation_id": response.correlation_id,
        }

    def handle_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
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
        try:
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
