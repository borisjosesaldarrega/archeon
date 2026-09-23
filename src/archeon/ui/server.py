"""Loopback-only UI server using the standard library and SSE events."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import urllib.request
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
from archeon.core.paths import AppPaths, ResourceManager


UI_ROOT = ResourceManager(AppPaths.discover()).ui_dir
MAX_BODY_BYTES = 32 * 1024


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class UIServer(ManagedComponent):
    def __init__(
        self,
        events: EventBus,
        *,
        command_handler: Callable[[str, list[str]], dict[str, Any]],
        action_handler: Callable[[str, dict[str, Any]], dict[str, Any]],
        health_handler: Callable[[], dict[str, Any]],
        auth_handler: Callable[[str, dict[str, Any], str], dict[str, Any]],
        session_handler: Callable[[str], dict[str, Any]],
        attachment_handler: Callable[[str, str, int, Any], dict[str, Any]] | None = None,
        cloud_upload_handler: Callable[[str, str, int, Any, str, str], dict[str, Any]] | None = None,
        media_resource_handler: Callable[[str], tuple[str, bytes] | None] | None = None,
        media_stream_handler: Callable[[], str | Path | None] | None = None,
        personalization_resource_handler: Callable[[str], Path | None] | None = None,
        port: int = 0,
        ui_root: Path | None = None,
    ) -> None:
        super().__init__("ui_server")
        self._events = events
        self._command_handler = command_handler
        self._action_handler = action_handler
        self._health_handler = health_handler
        self._auth_handler = auth_handler
        self._session_handler = session_handler
        self._attachment_handler = attachment_handler
        self._cloud_upload_handler = cloud_upload_handler
        self._media_resource_handler = media_resource_handler
        self._media_stream_handler = media_stream_handler
        self._personalization_resource_handler = personalization_resource_handler
        self._requested_port = port
        self._ui_root = (ui_root or UI_ROOT).resolve()
        # Android debug builds connect through ``adb reverse`` and need the
        # same short-lived token as the desktop runtime. Production keeps the
        # cryptographically random per-process token.
        development_token = os.environ.get("ARCHEON_DEV_UI_TOKEN", "").strip()
        self._token = development_token if len(development_token) >= 24 else secrets.token_urlsafe(24)
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
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data: blob: https://i.ytimg.com; media-src 'self' blob:; "
                    "connect-src 'self'; frame-src https://www.youtube.com https://www.youtube-nocookie.com",
                )
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                if length is not None:
                    self.send_header("Content-Length", str(length))

            def _authorized(self) -> bool:
                header = self.headers.get("X-Archeon-Token", "")
                query = parse_qs(urlparse(self.path).query)
                candidate = header or query.get("token", [""])[0]
                return secrets.compare_digest(candidate, owner.token)

            def _session_authorized(self) -> bool:
                token = self.headers.get("X-Archeon-Session", "")
                value = owner._session_handler(token)
                session = value.get("session") if isinstance(value, dict) else None
                return bool(value.get("ok") and isinstance(session, dict) and not session.get("mfa_required"))

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
                    if not self._authorized():
                        self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
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
                if path == "/media/current":
                    if not self._authorized() or owner._media_stream_handler is None:
                        self.send_error(HTTPStatus.UNAUTHORIZED)
                        return
                    source = owner._media_stream_handler()
                    if source is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    source_text = str(source)
                    if source_text.lower().startswith("https://"):
                        request_headers = {
                            "Accept": "audio/*,*/*;q=0.8",
                            "User-Agent": "ARCHEON-Mobile/0.1",
                        }
                        range_header = self.headers.get("Range", "")
                        if range_header.startswith("bytes="):
                            request_headers["Range"] = range_header
                        request = urllib.request.Request(source_text, headers=request_headers)
                        try:
                            with urllib.request.urlopen(request, timeout=20) as response:
                                status = HTTPStatus.PARTIAL_CONTENT if getattr(response, "status", 200) == 206 else HTTPStatus.OK
                                length_header = response.headers.get("Content-Length")
                                length = int(length_header) if length_header and length_header.isdigit() else None
                                self.send_response(status)
                                self._security_headers(response.headers.get_content_type() or "audio/mpeg", length)
                                self.send_header("Accept-Ranges", response.headers.get("Accept-Ranges", "bytes"))
                                content_range = response.headers.get("Content-Range")
                                if content_range:
                                    self.send_header("Content-Range", content_range)
                                self.send_header("Cache-Control", "no-store")
                                self.end_headers()
                                while True:
                                    chunk = response.read(64 * 1024)
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                        except (OSError, ValueError):
                            self.send_error(HTTPStatus.BAD_GATEWAY)
                        return
                    try:
                        file_path = Path(source_text).expanduser().resolve(strict=True)
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    if not file_path.is_file():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    size = file_path.stat().st_size
                    start, end, status = 0, max(0, size - 1), HTTPStatus.OK
                    range_header = self.headers.get("Range", "")
                    if range_header.startswith("bytes="):
                        try:
                            left, right = range_header[6:].split("-", 1)
                            start = int(left or 0)
                            end = min(size - 1, int(right) if right else size - 1)
                            if start < 0 or end < start or start >= size:
                                raise ValueError
                            status = HTTPStatus.PARTIAL_CONTENT
                        except ValueError:
                            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                            return
                    length = end - start + 1
                    self.send_response(status)
                    self._security_headers(mimetypes.guess_type(file_path.name)[0] or "audio/mpeg", length)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    if status == HTTPStatus.PARTIAL_CONTENT:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    with file_path.open("rb") as stream:
                        stream.seek(start)
                        remaining = length
                        while remaining:
                            chunk = stream.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
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
                if path.startswith("/personalization/"):
                    if not self._authorized() or owner._personalization_resource_handler is None:
                        self.send_error(HTTPStatus.UNAUTHORIZED)
                        return
                    file_path = owner._personalization_resource_handler(path.removeprefix("/personalization/"))
                    if file_path is None or not file_path.is_file():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    size = file_path.stat().st_size
                    start, end, status = 0, max(0, size - 1), HTTPStatus.OK
                    range_header = self.headers.get("Range", "")
                    if range_header.startswith("bytes="):
                        try:
                            left, right = range_header[6:].split("-", 1)
                            start = int(left or 0)
                            end = min(size - 1, int(right) if right else size - 1)
                            if start < 0 or end < start or start >= size:
                                raise ValueError
                            status = HTTPStatus.PARTIAL_CONTENT
                        except ValueError:
                            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                            return
                    length = end - start + 1
                    self.send_response(status)
                    self._security_headers(mimetypes.guess_type(file_path.name)[0] or "application/octet-stream", length)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "private, max-age=3600")
                    if status == HTTPStatus.PARTIAL_CONTENT:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    with file_path.open("rb") as source:
                        source.seek(start)
                        remaining = length
                        while remaining:
                            chunk = source.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
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
                file_path = owner._ui_root / target
                if not file_path.is_file() or owner._ui_root not in file_path.resolve().parents:
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
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/attachment":
                    if not self._session_authorized():
                        self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                        return
                    if owner._attachment_handler is None:
                        self._json({"ok": False, "error": "attachments_unavailable"}, HTTPStatus.NOT_IMPLEMENTED)
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        length = 0
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    result = owner._attachment_handler(
                        name,
                        self.headers.get("Content-Type", "application/octet-stream"),
                        length,
                        self.rfile,
                    )
                    self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/cloud-file":
                    if not self._session_authorized():
                        self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                        return
                    if owner._cloud_upload_handler is None:
                        self._json({"ok": False, "error": "cloud_upload_unavailable"}, HTTPStatus.NOT_IMPLEMENTED)
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        length = 0
                    query = parse_qs(parsed.query)
                    result = owner._cloud_upload_handler(
                        query.get("name", [""])[0],
                        self.headers.get("Content-Type", "application/octet-stream"),
                        length,
                        self.rfile,
                        self.headers.get("X-Archeon-Session", ""),
                        query.get("conversation_id", [""])[0],
                    )
                    self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                payload = self._read_json()
                if payload is None:
                    self._json({"ok": False, "error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
                    return
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
                    # Permit long assignments and pasted instructions without
                    # silently truncating them, while remaining below MAX_BODY.
                    if not isinstance(text, str) or not text.strip() or len(text) > 16_000:
                        self._json({"ok": False, "error": "invalid text"}, HTTPStatus.BAD_REQUEST)
                        return
                    attachment_ids = payload.get("attachments", [])
                    if not isinstance(attachment_ids, list) or not all(isinstance(value, str) for value in attachment_ids):
                        self._json({"ok": False, "error": "invalid attachments"}, HTTPStatus.BAD_REQUEST)
                        return
                    self._json(owner._command_handler(text, attachment_ids))
                    return
                if path == "/api/action":
                    if not self._session_authorized():
                        self._json({"ok": False, "error": "session_required"}, HTTPStatus.UNAUTHORIZED)
                        return
                    action = payload.get("action")
                    if not isinstance(action, str):
                        self._json({"ok": False, "error": "invalid action"}, HTTPStatus.BAD_REQUEST)
                        return
                    payload["_session_token"] = self.headers.get("X-Archeon-Session", "")
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
                session_state = owner._session_handler(session_token)
                if not session_state.get("ok") or (session_state.get("session") or {}).get("mfa_required"):
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
