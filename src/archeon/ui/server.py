"""Loopback-only UI server using the standard library and SSE events."""

from __future__ import annotations

import json
import mimetypes
import secrets
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty
from threading import Event as ThreadEvent
from threading import RLock, Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent


UI_ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 32 * 1024


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class UIServer(ManagedComponent):
    def __init__(
        self,
        events: EventBus,
        *,
        command_handler: Callable[[str], dict[str, Any]],
        action_handler: Callable[[str, dict[str, Any]], dict[str, Any]],
        health_handler: Callable[[], dict[str, Any]],
        auth_handler: Callable[[str, dict[str, Any], str], dict[str, Any]],
        session_handler: Callable[[str], dict[str, Any]],
        media_resource_handler: Callable[[str], tuple[str, bytes] | None] | None = None,
        port: int = 0,
    ) -> None:
        super().__init__("ui_server")
        self._events = events
        self._command_handler = command_handler
        self._action_handler = action_handler
        self._health_handler = health_handler
        self._auth_handler = auth_handler
        self._session_handler = session_handler
        self._media_resource_handler = media_resource_handler
        self._requested_port = port
        self._token = secrets.token_urlsafe(24)
        self._server: _Server | None = None
        self._thread: Thread | None = None
        self._stopping = ThreadEvent()
        self._continuation_session: str | None = None
        self._continuation_lock = RLock()

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("UI server is not running")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def thread_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _start(self) -> None:
        self._stopping.clear()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ArcheonUI/1"

            def log_message(self, format: str, *args: object) -> None:
                return None

            def _security_headers(self, content_type: str, length: int | None = None) -> None:
                self.send_header("Content-Type", content_type)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data: blob:; connect-src 'self'",
                )
                if length is not None:
                    self.send_header("Content-Length", str(length))

            def _authorized(self) -> bool:
                header = self.headers.get("X-Archeon-Token", "")
                query = parse_qs(urlparse(self.path).query)
                candidate = header or query.get("token", [""])[0]
                return secrets.compare_digest(candidate, owner.token)

            def _session_authorized(self) -> bool:
                token = self.headers.get("X-Archeon-Session", "")
                return bool(owner._session_handler(token).get("ok"))

            def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self._security_headers("application/json; charset=utf-8", len(body))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return None
                if length < 1 or length > MAX_BODY_BYTES:
                    return None
                try:
                    value = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return value if isinstance(value, dict) else None

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                path = urlparse(self.path).path
                if path == "/runtime-config.js":
                    with owner._continuation_lock:
                        continuation = owner._continuation_session
                        owner._continuation_session = None
                    body = (
                        "window.ARCHEON_RUNTIME="
                        + json.dumps({"token": owner.token, "resumeSession": continuation})
                        + ";"
                    ).encode()
                    self.send_response(HTTPStatus.OK)
                    self._security_headers("application/javascript; charset=utf-8", len(body))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/health":
                    if not self._authorized():
                        self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    self._json(owner._health_handler())
                    return
                if path == "/api/session":
                    if not self._authorized():
                        self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    self._json(owner._session_handler(self.headers.get("X-Archeon-Session", "")))
                    return
                if path == "/events":
                    self._serve_events()
                    return
                if path.startswith("/media/art/"):
                    if not self._authorized() or owner._media_resource_handler is None:
                        self.send_error(HTTPStatus.UNAUTHORIZED)
                        return
                    resource = owner._media_resource_handler(path.removeprefix("/media/art/"))
                    if resource is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    content_type, body = resource
                    self.send_response(HTTPStatus.OK)
                    self._security_headers(content_type, len(body))
                    self.send_header("Cache-Control", "private, max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                target = {
                    "/": "index.html",
                    "/index.html": "index.html",
                    "/ghost": "ghost.html",
                    "/ghost.html": "ghost.html",
                }.get(path, path.lstrip("/"))
                if not target or ".." in Path(target).parts:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                file_path = UI_ROOT / target
                if not file_path.is_file() or UI_ROOT not in file_path.resolve().parents:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body = file_path.read_bytes()
                content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self._security_headers(content_type, len(body))
                # UI files must update as one version after an application upgrade.
                # They are local and small, so revalidation is cheaper than a mixed,
                # stale HTML/JavaScript interface.
                self.send_header("Cache-Control", "no-cache, must-revalidate")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                if not self._authorized():
                    self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                payload = self._read_json()
                if payload is None:
                    self._json({"ok": False, "error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
                    return
                path = urlparse(self.path).path
                if path.startswith("/api/auth/"):
                    operation = path.removeprefix("/api/auth/")
                    result = owner._auth_handler(
                        operation,
                        payload,
                        self.headers.get("X-Archeon-Session", ""),
                    )
                    self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/command":
                    if not self._session_authorized():
                        self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                        return
                    text = payload.get("text")
                    if not isinstance(text, str) or not text.strip() or len(text) > 2_000:
                        self._json({"ok": False, "error": "invalid text"}, HTTPStatus.BAD_REQUEST)
                        return
                    self._json(owner._command_handler(text))
                    return
                if path == "/api/action":
                    if not self._session_authorized():
                        self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                        return
                    action = payload.get("action")
                    if not isinstance(action, str):
                        self._json({"ok": False, "error": "invalid action"}, HTTPStatus.BAD_REQUEST)
                        return
                    result = owner._action_handler(action, payload)
                    if result.get("ok") and action == "window.ghost":
                        with owner._continuation_lock:
                            owner._continuation_session = self.headers.get("X-Archeon-Session", "")
                    self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _serve_events(self) -> None:
                if not self._authorized():
                    self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                query = parse_qs(urlparse(self.path).query)
                session_token = query.get("session", [""])[0]
                if not owner._session_handler(session_token).get("ok"):
                    self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                    return
                self.send_response(HTTPStatus.OK)
                self._security_headers("text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                subscription = owner._events.subscribe("*", max_queue=64)
                try:
                    self.wfile.write(b"retry: 3000\n\n")
                    self.wfile.flush()
                    while not owner._stopping.is_set():
                        try:
                            event = subscription.get(timeout=15.0)
                            data = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
                            chunk = f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n".encode("utf-8")
                        except Empty:
                            chunk = b": keepalive\n\n"
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, RuntimeError, OSError):
                    pass
                finally:
                    subscription.close()

        self._server = _Server(("127.0.0.1", self._requested_port), Handler)
        self._thread = Thread(target=self._server.serve_forever, name="archeon-ui-server", daemon=False)
        self._thread.start()

    def _stop(self) -> None:
        self._stopping.set()
        self._events.publish("ui.server.stopping", source="ui_server")
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise RuntimeError("UI server thread did not stop")
        self._server = None
        self._thread = None
