"""Lightweight authentication with Supabase and Windows-protected sessions."""

from __future__ import annotations

import ctypes
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from archeon.core.events import EventBus
from archeon.core.lifecycle import ManagedComponent
from archeon.auth.email import normalize_email


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ProviderSession:
    identity: Identity
    access_token: str = ""
    refresh_token: str = ""
    expires_at: int = 0
    email_verified: bool = False
    pending_confirmation: bool = False
    mfa_required: bool = False


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    identity: Identity
    mode: str
    email_verified: bool = False
    pending_confirmation: bool = False
    mfa_required: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "identity": asdict(self.identity),
            "email_verified": self.email_verified,
            "pending_confirmation": self.pending_confirmation,
            "mfa_required": self.mfa_required,
        }


class AuthProvider(Protocol):
    name: str

    def register(self, email: str, password: str, display_name: str, locale: str = "es") -> ProviderSession: ...
    def login(self, email: str, password: str) -> ProviderSession: ...
    def restore(self, refresh_token: str) -> ProviderSession: ...
    def refresh(self, refresh_token: str) -> ProviderSession: ...
    def forgot_password(self, email: str) -> None: ...
    def reset_password(self, email: str, token: str, password: str) -> None: ...
    def verify_signup(self, email: str, token: str) -> ProviderSession: ...
    def resend_signup(self, email: str) -> None: ...
    def reauthenticate(self, access_token: str) -> None: ...
    def update_user(self, access_token: str, changes: dict[str, str]) -> ProviderSession: ...
    def logout(self, access_token: str = "", scope: str = "global") -> None: ...
    def mfa_enroll(self, access_token: str, friendly_name: str) -> dict[str, Any]: ...
    def mfa_verify(self, access_token: str, factor_id: str, code: str) -> ProviderSession: ...
    def mfa_factors(self, access_token: str) -> list[dict[str, Any]]: ...
    def mfa_unenroll(self, access_token: str, factor_id: str) -> None: ...
    def delete_account(self, access_token: str) -> None: ...


class SessionVault(Protocol):
    def save(self, value: dict[str, Any]) -> None: ...
    def load(self) -> dict[str, Any] | None: ...
    def clear(self) -> None: ...


class MemorySessionVault:
    """Non-persistent vault for tests and unsupported platforms."""

    def __init__(self) -> None:
        self._value: dict[str, Any] | None = None

    def save(self, value: dict[str, Any]) -> None:
        self._value = dict(value)

    def load(self) -> dict[str, Any] | None:
        return dict(self._value) if self._value else None

    def clear(self) -> None:
        self._value = None


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte)))


class WindowsDpapiSessionVault:
    """Persist a small session envelope encrypted for the current Windows user."""

    def __init__(self, path: Path) -> None:
        if os.name != "nt":
            raise OSError("dpapi_requires_windows")
        self._path = path
        self._lock = RLock()

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(value)
        return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer

    @classmethod
    def _protect(cls, value: bytes) -> bytes:
        source, source_buffer = cls._blob(value)
        output = _DataBlob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "ARCHEON Supabase session", None, None, None, 0x1, ctypes.byref(output)
        )
        del source_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)

    @staticmethod
    def _unprotect(value: bytes) -> bytes:
        source, source_buffer = WindowsDpapiSessionVault._blob(value)
        output = _DataBlob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)
        )
        del source_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)

    def save(self, value: dict[str, Any]) -> None:
        encrypted = self._protect(json.dumps(value, separators=(",", ":")).encode())
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_bytes(encrypted)
            os.replace(temporary, self._path)

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._path.exists():
                return None
            encrypted = self._path.read_bytes()
        try:
            value = json.loads(self._unprotect(encrypted).decode())
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self.clear()
            return None
        return value if isinstance(value, dict) else None

    def clear(self) -> None:
        with self._lock:
            self._path.unlink(missing_ok=True)


class DevelopmentAuthProvider:
    """Local test provider retained for deterministic tests, not production composition."""

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
        return normalize_email(email, reject_disposable=True)

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)

    def register(self, email: str, password: str, display_name: str, locale: str = "es") -> ProviderSession:
        normalized = self._normalize(email)
        if len(password) < 10:
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
        return ProviderSession(identity, email_verified=True)

    def login(self, email: str, password: str) -> ProviderSession:
        normalized = self._normalize(email)
        with self._lock:
            record = self._read().get("accounts", {}).get(normalized)
        if not isinstance(record, dict):
            raise ValueError("invalid_credentials")
        salt = bytes.fromhex(record["salt"])
        if not hmac.compare_digest(self._derive(password, salt).hex(), str(record["password_hash"])):
            raise ValueError("invalid_credentials")
        identity = Identity(str(record["user_id"]), normalized, str(record["display_name"]))
        return ProviderSession(identity, email_verified=True)

    def restore(self, refresh_token: str) -> ProviderSession:
        raise ValueError("session_unavailable")

    refresh = restore

    def forgot_password(self, email: str) -> None:
        raise ValueError("cloud_auth_unavailable")

    def reset_password(self, email: str, token: str, password: str) -> None:
        raise ValueError("cloud_auth_unavailable")

    def verify_signup(self, email: str, token: str) -> ProviderSession:
        raise ValueError("cloud_auth_unavailable")

    def resend_signup(self, email: str) -> None:
        raise ValueError("cloud_auth_unavailable")

    def reauthenticate(self, access_token: str) -> None:
        raise ValueError("cloud_auth_unavailable")

    def update_user(self, access_token: str, changes: dict[str, str]) -> ProviderSession:
        raise ValueError("cloud_auth_unavailable")

    def logout(self, access_token: str = "", scope: str = "global") -> None:
        return None

    def mfa_enroll(self, access_token: str, friendly_name: str) -> dict[str, Any]:
        raise ValueError("cloud_auth_unavailable")

    def mfa_verify(self, access_token: str, factor_id: str, code: str) -> ProviderSession:
        raise ValueError("cloud_auth_unavailable")

    def mfa_factors(self, access_token: str) -> list[dict[str, Any]]:
        return []

    def mfa_unenroll(self, access_token: str, factor_id: str) -> None:
        raise ValueError("cloud_auth_unavailable")

    def delete_account(self, access_token: str) -> None:
        raise ValueError("cloud_auth_unavailable")


class SupabaseAuthProvider:
    """Dependency-free GoTrue adapter loaded only for account actions."""

    name = "supabase"

    def __init__(self, url: str, publishable_key: str, *, timeout: float = 8.0) -> None:
        self._url = url.rstrip("/")
        self._key = publishable_key.strip()
        self._timeout = timeout
        if not self._url.startswith("https://") or not self._key:
            raise ValueError("supabase_not_configured")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, access_token: str = "") -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"apikey": self._key, "Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {access_token or self._key}"
        endpoint = f"{self._url}{path}" if path.startswith("/") else f"{self._url}/auth/v1/{path}"
        request = Request(endpoint, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode())
            except (UnicodeError, ValueError, json.JSONDecodeError):
                detail = {}
            # GoTrue commonly returns a numeric HTTP-style ``code`` together
            # with the stable machine-readable ``error_code``.  Showing the
            # numeric value (for example ``400``) leaves both UIs without an
            # actionable message, so prefer the documented auth error code.
            raw_code = detail.get("error_code") or detail.get("code")
            code = str(raw_code) if isinstance(raw_code, str) and raw_code else "auth_request_failed"
            policy_message = str(detail.get("msg") or detail.get("message") or "")
            if policy_message in {"account_exists", "disposable_email_not_allowed"}:
                code = policy_message
            if error.code == 429:
                code = "auth_rate_limited"
            raise ValueError(code) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("auth_offline") from None
        if not raw:
            return {}
        value = json.loads(raw.decode())
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _result(value: dict[str, Any]) -> ProviderSession:
        user = value.get("user") if isinstance(value.get("user"), dict) else value
        metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
        email = str(user.get("email") or "")
        identity = Identity(
            str(user.get("id") or ""), email,
            str(metadata.get("display_name") or email.split("@", 1)[0] or "Usuario"),
        )
        access_token = str(value.get("access_token") or "")
        factors = user.get("factors") if isinstance(user.get("factors"), list) else []
        has_verified_factor = any(
            isinstance(factor, dict) and str(factor.get("status") or "").casefold() == "verified"
            for factor in factors
        )
        assurance = ""
        if access_token:
            try:
                segment = access_token.split(".")[1]
                padding = "=" * (-len(segment) % 4)
                claims = json.loads(base64.urlsafe_b64decode(segment + padding).decode("utf-8"))
                assurance = str(claims.get("aal") or "") if isinstance(claims, dict) else ""
            except (IndexError, UnicodeError, ValueError, json.JSONDecodeError):
                assurance = ""
        return ProviderSession(
            identity, access_token, str(value.get("refresh_token") or ""),
            int(value.get("expires_at") or (time.time() + int(value.get("expires_in") or 0))),
            bool(user.get("email_confirmed_at") or user.get("confirmed_at")), not access_token,
            has_verified_factor and assurance != "aal2",
        )

    def register(self, email: str, password: str, display_name: str, locale: str = "es") -> ProviderSession:
        email = normalize_email(email, reject_disposable=True)
        if len(password) < 10:
            raise ValueError("password_too_short")
        if not display_name.strip() or len(display_name.strip()) > 40:
            raise ValueError("invalid_display_name")
        language = locale.strip().lower() if locale.strip().lower() in {"es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi"} else "es"
        return self._result(self._request("POST", "signup", {"email": email, "password": password, "data": {"display_name": display_name, "locale": language}}))

    def login(self, email: str, password: str) -> ProviderSession:
        email = normalize_email(email, canonical_aliases=False)
        return self._result(self._request("POST", f"token?{urlencode({'grant_type': 'password'})}", {"email": email, "password": password}))

    def restore(self, refresh_token: str) -> ProviderSession:
        return self.refresh(refresh_token)

    def refresh(self, refresh_token: str) -> ProviderSession:
        return self._result(self._request("POST", f"token?{urlencode({'grant_type': 'refresh_token'})}", {"refresh_token": refresh_token}))

    def forgot_password(self, email: str) -> None:
        self._request("POST", "recover", {"email": normalize_email(email, canonical_aliases=False)})

    def reset_password(self, email: str, token: str, password: str) -> None:
        code = token.strip()
        if len(code) != 8 or not code.isdecimal():
            raise ValueError("invalid_verification_code")
        if len(password) < 10:
            raise ValueError("password_too_short")
        verified = self._request(
            "POST",
            "verify",
            {"email": normalize_email(email), "token": code, "type": "recovery"},
        )
        access_token = str(verified.get("access_token") or "")
        if not access_token:
            raise ValueError("invalid_verification_code")
        self._request("PUT", "user", {"password": password}, access_token=access_token)
        # Recovery tokens are single-purpose. End the temporary provider session
        # so password recovery never signs ARCHEON in implicitly.
        self.logout(access_token, "local")

    def verify_signup(self, email: str, token: str) -> ProviderSession:
        code = token.strip()
        if len(code) != 8 or not code.isdecimal():
            raise ValueError("invalid_verification_code")
        return self._result(
            self._request(
                "POST",
                "verify",
                {"email": normalize_email(email), "token": code, "type": "signup"},
            )
        )

    def resend_signup(self, email: str) -> None:
        self._request("POST", "resend", {"email": normalize_email(email), "type": "signup"})

    def reauthenticate(self, access_token: str) -> None:
        self._request("POST", "reauthenticate", {}, access_token=access_token)

    def update_user(self, access_token: str, changes: dict[str, str]) -> ProviderSession:
        return self._result(self._request("PUT", "user", changes, access_token=access_token))

    def logout(self, access_token: str = "", scope: str = "global") -> None:
        if access_token:
            self._request("POST", f"logout?{urlencode({'scope': scope})}", {}, access_token=access_token)

    def mfa_enroll(self, access_token: str, friendly_name: str) -> dict[str, Any]:
        return self._request("POST", "factors", {"factor_type": "totp", "friendly_name": friendly_name}, access_token=access_token)

    def mfa_factors(self, access_token: str) -> list[dict[str, Any]]:
        user = self._request("GET", "user", access_token=access_token)
        factors = user.get("factors", [])
        return [factor for factor in factors if isinstance(factor, dict)]

    def mfa_verify(self, access_token: str, factor_id: str, code: str) -> ProviderSession:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", factor_id):
            raise ValueError("invalid_mfa_factor")
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("invalid_mfa_code")
        challenge = self._request("POST", f"factors/{factor_id}/challenge", {}, access_token=access_token)
        verified = self._request("POST", f"factors/{factor_id}/verify", {"challenge_id": challenge.get("id"), "code": code}, access_token=access_token)
        return self._result(verified)

    def mfa_unenroll(self, access_token: str, factor_id: str) -> None:
        self._request("DELETE", f"factors/{factor_id}", access_token=access_token)

    def delete_account(self, access_token: str) -> None:
        self._request("POST", "/rest/v1/rpc/delete_own_account", {}, access_token=access_token)


class UnconfiguredAuthProvider:
    """Guest-safe provider used when no real account backend is configured."""

    name = "not_configured"

    @staticmethod
    def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("auth_backend_not_configured")

    register = login = restore = refresh = forgot_password = reset_password = _unavailable
    verify_signup = resend_signup = reauthenticate = update_user = _unavailable
    mfa_enroll = mfa_verify = mfa_unenroll = delete_account = _unavailable

    def mfa_factors(self, _access_token: str) -> list[dict[str, Any]]:
        return []

    def logout(self, access_token: str = "", scope: str = "global") -> None:
        return None


class AuthManager(ManagedComponent):
    def __init__(self, events: EventBus, provider: AuthProvider, vault: SessionVault | None = None) -> None:
        super().__init__("auth")
        self._events = events
        self._provider = provider
        self._vault = vault or MemorySessionVault()
        self._sessions: dict[str, Session] = {}
        self._provider_sessions: dict[str, ProviderSession] = {}
        self._lock = RLock()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def guest(self) -> Session:
        return self._create(ProviderSession(Identity(f"guest-{secrets.token_hex(8)}", "", "Invitado")), "guest")

    def register(self, email: str, password: str, display_name: str, locale: str = "es") -> Session:
        return self._create(self._provider.register(email, password, display_name, locale), "account")

    def login(self, email: str, password: str) -> Session:
        return self._create(self._provider.login(email, password), "account")

    def restore(self) -> Session | None:
        envelope = self._vault.load()
        if not envelope:
            return None
        if envelope.get("mode") == "guest":
            user_id = str(envelope.get("user_id") or f"guest-{secrets.token_hex(8)}")
            return self._create(ProviderSession(Identity(user_id, "", "Invitado")), "guest")
        if not isinstance(envelope.get("refresh_token"), str):
            self._vault.clear()
            return None
        try:
            return self._create(self._provider.restore(envelope["refresh_token"]), "account")
        except ValueError as error:
            if str(error) != "auth_offline":
                self._vault.clear()
            raise

    def refresh(self, token: str) -> Session:
        current = self._provider_for(token)
        return self._replace(token, self._provider.refresh(current.refresh_token))

    def forgot_password(self, email: str) -> None:
        self._provider.forgot_password(email)

    def reset_password(self, email: str, token: str, password: str) -> None:
        self._provider.reset_password(email, token, password)

    def verify_signup(self, email: str, token: str) -> Session:
        return self._create(self._provider.verify_signup(email, token), "account")

    def resend_signup(self, email: str) -> None:
        self._provider.resend_signup(email)

    def reauthenticate(self, token: str) -> None:
        self._provider.reauthenticate(self._provider_for(token).access_token)

    def update_user(self, token: str, changes: dict[str, str]) -> Session:
        current = self._provider_for(token)
        updated = self._provider.update_user(current.access_token, changes)
        if not updated.access_token:
            updated = ProviderSession(updated.identity, current.access_token, current.refresh_token, current.expires_at, updated.email_verified, updated.pending_confirmation, updated.mfa_required)
        return self._replace(token, updated)

    def get(self, token: str) -> Session | None:
        with self._lock:
            return self._sessions.get(token)

    def cloud_identity(self, token: str) -> tuple[Identity, str]:
        """Return a fresh provider credential for an internal authenticated request."""
        current = self._provider_for(token)
        if current.mfa_required:
            raise ValueError("mfa_verification_required")
        if current.expires_at and current.expires_at <= int(time.time()) + 30:
            updated = self._provider.refresh(current.refresh_token)
            with self._lock:
                if token not in self._sessions:
                    raise ValueError("session_required")
                self._provider_sessions[token] = updated
                self._sessions[token] = Session(
                    token, updated.identity, "account", updated.email_verified, updated.pending_confirmation,
                    updated.mfa_required,
                )
            if updated.refresh_token:
                self._vault.save({
                    "mode": "account",
                    "refresh_token": updated.refresh_token,
                    "user_id": updated.identity.user_id,
                    "saved_at": int(time.time()),
                })
            current = updated
        if not current.access_token:
            raise ValueError("account_session_required")
        return current.identity, current.access_token

    def logout(self, token: str, *, scope: str = "global") -> bool:
        with self._lock:
            session = self._sessions.pop(token, None)
            provider_session = self._provider_sessions.pop(token, None)
        if session is None:
            return False
        try:
            if session.mode == "account" and provider_session:
                self._provider.logout(provider_session.access_token, scope)
        finally:
            self._vault.clear()
        self._events.publish("auth.session.ended", {"mode": session.mode}, source="auth")
        return True

    def logout_others(self, token: str) -> bool:
        current = self._provider_for(token)
        self._provider.logout(current.access_token, "others")
        self._events.publish("auth.sessions.others_ended", source="auth")
        return True

    def mfa_status(self, token: str) -> list[dict[str, Any]]:
        current = self._provider_for(token)
        return self._provider.mfa_factors(current.access_token)

    def mfa_enroll(self, token: str, friendly_name: str) -> dict[str, Any]:
        current = self._provider_for(token)
        return self._provider.mfa_enroll(current.access_token, friendly_name[:40] or "ARCHEON Windows")

    def mfa_verify(self, token: str, factor_id: str, code: str) -> Session:
        current = self._provider_for(token)
        return self._replace(token, self._provider.mfa_verify(current.access_token, factor_id, code))

    def mfa_unenroll(self, token: str, factor_id: str) -> None:
        current = self._provider_for(token)
        self._provider.mfa_unenroll(current.access_token, factor_id)

    def delete_account(self, token: str) -> bool:
        current = self._provider_for(token)
        self._provider.delete_account(current.access_token)
        with self._lock:
            removed = self._sessions.pop(token, None)
            self._provider_sessions.pop(token, None)
        self._vault.clear()
        self._events.publish("auth.account.deleted", source="auth")
        return removed is not None

    def _provider_for(self, token: str) -> ProviderSession:
        with self._lock:
            value = self._provider_sessions.get(token)
        if value is None or not value.refresh_token:
            raise ValueError("account_session_required")
        return value

    def _replace(self, token: str, provider_session: ProviderSession) -> Session:
        with self._lock:
            old = self._sessions.pop(token, None)
            self._provider_sessions.pop(token, None)
        if old is None:
            raise ValueError("session_required")
        return self._create(provider_session, "account")

    def _create(self, provider_session: ProviderSession, mode: str) -> Session:
        session = Session(secrets.token_urlsafe(32), provider_session.identity, mode, provider_session.email_verified, provider_session.pending_confirmation, provider_session.mfa_required)
        with self._lock:
            self._sessions[session.token] = session
            if mode == "account":
                self._provider_sessions[session.token] = provider_session
        if mode == "account" and provider_session.refresh_token:
            self._vault.save({"mode": "account", "refresh_token": provider_session.refresh_token, "user_id": provider_session.identity.user_id, "saved_at": int(time.time())})
        elif mode == "guest":
            self._vault.save({"mode": "guest", "user_id": provider_session.identity.user_id, "saved_at": int(time.time())})
        self._events.publish("auth.session.started", {"mode": mode}, source="auth")
        return session

    def _start(self) -> None:
        return None

    def _stop(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._provider_sessions.clear()
