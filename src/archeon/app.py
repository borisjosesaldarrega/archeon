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
from archeon.core.permissions import PermissionEngine
from archeon.core.secure_logging import close_logger, configure_logging, log_event
from archeon.core.tools import ToolEngine
from archeon.database import DatabaseManager
from archeon.plugins import PluginManager
from archeon.system import DeviceSystemEngine
from archeon.ui.server import UIServer


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
        self.plugins = PluginManager(self.events, self.data_dir / "plugins")
        self.system = DeviceSystemEngine(self.tools)
        self.orchestrator = Orchestrator(self.events, self.tools)
        self.ui_server = UIServer(
            self.events,
            command_handler=self.handle_command,
            action_handler=self.handle_action,
            health_handler=self.health,
            auth_handler=self.handle_auth,
            session_handler=self.handle_session,
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

    def handle_action(self, action: str) -> dict[str, Any]:
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
        if action in {"music.started", "music.paused", "music.stopped"}:
            self.events.publish(
                action,
                {"title": "Pulso de ARCHEON", "artist": "Audio local bajo demanda"},
                source="application",
            )
            log_event(self.logger, action)
            return {"ok": True}
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
            "event_subscribers": self.events.subscriber_count,
        }

    def __enter__(self) -> ArcheonApplication:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
