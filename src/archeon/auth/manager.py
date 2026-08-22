"""Provider-based authentication with a fully local guest/development path."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    identity: Identity
    mode: str

    def public(self) -> dict[str, Any]:
        return {"mode": self.mode, "identity": asdict(self.identity)}


class AuthProvider(Protocol):
    name: str

    def register(self, email: str, password: str, display_name: str) -> Identity: ...
    def login(self, email: str, password: str) -> Identity: ...
    def logout(self, provider_token: str | None = None) -> None: ...


class DevelopmentAuthProvider:
    """Small local provider for exercising account UX without Firebase/cloud."""

    name = "development-local"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"accounts": {}}
        value = json.loads(self._path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"accounts": {}}

    def _write(self, value: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)

    @staticmethod
    def _normalize(email: str) -> str:
        normalized = email.strip().casefold()
        if "@" not in normalized or len(normalized) > 254:
            raise ValueError("invalid_email")
        return normalized

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)

    def register(self, email: str, password: str, display_name: str) -> Identity:
        normalized = self._normalize(email)
        if len(password) < 8:
            raise ValueError("password_too_short")
        name = display_name.strip()
        if not name or len(name) > 40:
            raise ValueError("invalid_display_name")
        with self._lock:
            data = self._read()
            accounts = data.setdefault("accounts", {})
            if normalized in accounts:
                raise ValueError("account_exists")
            salt = secrets.token_bytes(16)
            identity = Identity(secrets.token_hex(12), normalized, name)
            accounts[normalized] = {
                "user_id": identity.user_id,
                "display_name": name,
                "salt": salt.hex(),
                "password_hash": self._derive(password, salt).hex(),
            }
            self._write(data)
        return identity

    def login(self, email: str, password: str) -> Identity:
        normalized = self._normalize(email)
        with self._lock:
            record = self._read().get("accounts", {}).get(normalized)
        if not isinstance(record, dict):
            raise ValueError("invalid_credentials")
        salt = bytes.fromhex(record["salt"])
        actual = self._derive(password, salt)
        if not hmac.compare_digest(actual.hex(), str(record["password_hash"])):
            raise ValueError("invalid_credentials")
        return Identity(str(record["user_id"]), normalized, str(record["display_name"]))

    def logout(self, provider_token: str | None = None) -> None:
        return None


class SupabaseAuthProvider:
    """Auth-only adapter; it assumes no application tables or custom schema."""

    name = "supabase"

    def __init__(self, client: Any) -> None:
        self._client = client

    def register(self, email: str, password: str, display_name: str) -> Identity:
        result = self._client.auth.sign_up(
            {"email": email, "password": password, "options": {"data": {"display_name": display_name}}}
        )
        user = result.user
        return Identity(str(user.id), str(user.email), display_name)

    def login(self, email: str, password: str) -> Identity:
        result = self._client.auth.sign_in_with_password({"email": email, "password": password})
        user = result.user
        metadata = getattr(user, "user_metadata", {}) or {}
        return Identity(str(user.id), str(user.email), str(metadata.get("display_name", user.email)))

    def logout(self, provider_token: str | None = None) -> None:
        self._client.auth.sign_out()


class AuthManager(ManagedComponent):
    def __init__(self, events: EventBus, provider: AuthProvider) -> None:
        super().__init__("auth")
        self._events = events
        self._provider = provider
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def guest(self) -> Session:
        identity = Identity(f"guest-{secrets.token_hex(8)}", "", "Invitado")
        return self._create(identity, "guest")

    def register(self, email: str, password: str, display_name: str) -> Session:
        return self._create(self._provider.register(email, password, display_name), "account")

    def login(self, email: str, password: str) -> Session:
        return self._create(self._provider.login(email, password), "account")

    def get(self, token: str) -> Session | None:
        with self._lock:
            return self._sessions.get(token)

    def logout(self, token: str) -> bool:
        with self._lock:
            session = self._sessions.pop(token, None)
        if session is None:
            return False
        if session.mode == "account":
            self._provider.logout()
        self._events.publish("auth.session.ended", {"mode": session.mode}, source="auth")
        return True

    def _create(self, identity: Identity, mode: str) -> Session:
        session = Session(secrets.token_urlsafe(32), identity, mode)
        with self._lock:
            self._sessions[session.token] = session
        self._events.publish("auth.session.started", {"mode": mode}, source="auth")
        return session

    def _start(self) -> None:
        return None

    def _stop(self) -> None:
        with self._lock:
            self._sessions.clear()
