from __future__ import annotations

import tempfile
import unittest
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from archeon.auth import AuthManager, DevelopmentAuthProvider, MemorySessionVault, SupabaseAuthProvider, UnconfiguredAuthProvider, WindowsDpapiSessionVault
from archeon.auth.email import normalize_email
from archeon.auth.manager import Identity, ProviderSession
from archeon.core.events import EventBus


class AuthTests(unittest.TestCase):
    def test_unconfigured_provider_keeps_guest_mode_but_rejects_cloud_auth(self) -> None:
        manager = AuthManager(EventBus(), UnconfiguredAuthProvider(), MemorySessionVault())
        self.assertEqual(manager.provider_name, "not_configured")
        self.assertEqual(manager.guest().mode, "guest")
        with self.assertRaisesRegex(ValueError, "auth_backend_not_configured"):
            manager.login("person@example.com", "safe-password")

    def test_development_provider_uses_the_same_ten_character_password_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = AuthManager(EventBus(), DevelopmentAuthProvider(Path(temporary) / "auth.json"))
            with self.assertRaisesRegex(ValueError, "password_too_short"):
                manager.register("person@example.com", "123456789", "Persona")

    def test_gmail_aliases_share_one_canonical_identity(self) -> None:
        self.assertEqual(normalize_email("Ex.Ample+news@googlemail.com"), "example@gmail.com")
        with tempfile.TemporaryDirectory() as temporary:
            manager = AuthManager(EventBus(), DevelopmentAuthProvider(Path(temporary) / "auth.json"))
            manager.register("ex.ample@gmail.com", "safe-password", "Persona")
            with self.assertRaisesRegex(ValueError, "account_exists"):
                manager.register("example+other@gmail.com", "safe-password", "Otra")

    def test_disposable_email_is_rejected_before_signup(self) -> None:
        with self.assertRaisesRegex(ValueError, "disposable_email_not_allowed"):
            normalize_email("person@mailinator.com", reject_disposable=True)
        with self.assertRaisesRegex(ValueError, "disposable_email_not_allowed"):
            normalize_email("person@sub.mailinator.com", reject_disposable=True)

    def test_login_can_preserve_a_legacy_gmail_spelling(self) -> None:
        self.assertEqual(
            normalize_email("Ex.Ample+old@gmail.com", canonical_aliases=False),
            "ex.ample+old@gmail.com",
        )

    def test_supabase_signup_verification_requires_eight_digits(self) -> None:
        class Provider(SupabaseAuthProvider):
            def __init__(self):
                super().__init__("https://example.supabase.co", "publishable")
                self.last_request = None

            def _request(self, method, path, payload=None, *, access_token=""):
                self.last_request = (method, path, payload)
                return {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "user": {"id": "user-a", "email": payload["email"], "email_confirmed_at": "now"},
                }

        provider = Provider()
        with self.assertRaisesRegex(ValueError, "invalid_verification_code"):
            provider.verify_signup("person@example.com", "123456")
        result = provider.verify_signup("person@example.com", "12345678")
        self.assertEqual(provider.last_request, ("POST", "verify", {"email": "person@example.com", "token": "12345678", "type": "signup"}))
        self.assertTrue(result.email_verified)

    def test_supabase_signup_persists_supported_email_locale(self) -> None:
        class Provider(SupabaseAuthProvider):
            def __init__(self):
                super().__init__("https://example.supabase.co", "publishable")
                self.payload = None

            def _request(self, method, path, payload=None, *, access_token=""):
                self.payload = payload
                return {"user": {"id": "pending", "email": payload["email"]}}

        provider = Provider()
        provider.register("person@example.com", "safe-password", "Persona", "en")
        self.assertEqual(provider.payload["data"]["locale"], "en")
        provider.register("other@example.com", "safe-password", "Persona", "unsupported")
        self.assertEqual(provider.payload["data"]["locale"], "es")

    def test_supabase_prefers_machine_readable_error_code_over_numeric_code(self) -> None:
        provider = SupabaseAuthProvider("https://example.supabase.co", "publishable")
        body = BytesIO(b'{"code":400,"error_code":"invalid_credentials","msg":"Invalid login credentials"}')
        error = HTTPError("https://example.supabase.co/auth/v1/token", 400, "Bad Request", {}, body)
        with patch("archeon.auth.manager.urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, "^invalid_credentials$"):
                provider._request("POST", "token?grant_type=password", {"email": "person@example.com"})

    def test_supabase_password_recovery_uses_eight_digit_code_without_persisting_session(self) -> None:
        class Provider(SupabaseAuthProvider):
            def __init__(self):
                super().__init__("https://example.supabase.co", "publishable")
                self.requests = []

            def _request(self, method, path, payload=None, *, access_token=""):
                self.requests.append((method, path, payload, access_token))
                if path == "verify":
                    return {"access_token": "temporary-recovery-token"}
                return {}

        provider = Provider()
        with self.assertRaisesRegex(ValueError, "invalid_verification_code"):
            provider.reset_password("person@example.com", "123456", "new-safe-password")
        provider.reset_password("person@example.com", "12345678", "new-safe-password")
        self.assertEqual(provider.requests[0], (
            "POST", "verify",
            {"email": "person@example.com", "token": "12345678", "type": "recovery"}, "",
        ))
        self.assertEqual(provider.requests[1], (
            "PUT", "user", {"password": "new-safe-password"}, "temporary-recovery-token",
        ))
        self.assertEqual(provider.requests[2][0:2], ("POST", "logout?scope=local"))

    def test_supabase_mfa_rejects_malformed_input_and_verifies_one_challenge(self) -> None:
        class Provider(SupabaseAuthProvider):
            def __init__(self):
                super().__init__("https://example.supabase.co", "publishable")
                self.requests = []

            def _request(self, method, path, payload=None, *, access_token=""):
                self.requests.append((method, path, payload, access_token))
                if path.endswith("/challenge"):
                    return {"id": "challenge-a"}
                return {
                    "access_token": "aal2-access", "refresh_token": "refresh", "expires_in": 3600,
                    "user": {"id": "user-a", "email": "person@example.com", "email_confirmed_at": "now"},
                }

        provider = Provider()
        with self.assertRaisesRegex(ValueError, "invalid_mfa_factor"):
            provider.mfa_verify("access", "../factor", "123456")
        with self.assertRaisesRegex(ValueError, "invalid_mfa_code"):
            provider.mfa_verify("access", "factor-a", "12345678")
        result = provider.mfa_verify("access", "factor-a", "123456")
        self.assertTrue(result.email_verified)
        self.assertEqual(provider.requests[0][1], "factors/factor-a/challenge")
        self.assertEqual(provider.requests[1][2], {"challenge_id": "challenge-a", "code": "123456"})

    def test_password_is_hashed_and_session_is_memory_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "auth.json"
            manager = AuthManager(EventBus(), DevelopmentAuthProvider(path))
            manager.start()
            session = manager.register("person@example.com", "safe-password", "Persona")
            stored = path.read_text(encoding="utf-8")
            self.assertNotIn("safe-password", stored)
            self.assertIsNotNone(manager.get(session.token))
            manager.stop()
            self.assertIsNone(manager.get(session.token))

    def test_account_session_restores_from_refresh_token_without_password(self) -> None:
        class Provider:
            name = "fake-cloud"

            def login(self, email, password):
                return ProviderSession(Identity("user-a", email, "A"), "access-1", "refresh-1", 100, True)

            def restore(self, refresh_token):
                self.restored = refresh_token
                return ProviderSession(Identity("user-a", "a@example.com", "A"), "access-2", "refresh-2", 200, True)

            refresh = restore

            def logout(self, access_token="", scope="global"): pass

        vault = MemorySessionVault()
        first_provider = Provider()
        first = AuthManager(EventBus(), first_provider, vault)
        first.login("a@example.com", "never-persist-this")
        envelope = vault.load()
        self.assertNotIn("password", envelope)
        self.assertEqual(envelope["refresh_token"], "refresh-1")

        second_provider = Provider()
        restored = AuthManager(EventBus(), second_provider, vault).restore()
        self.assertEqual(second_provider.restored, "refresh-1")
        self.assertEqual(restored.identity.user_id, "user-a")
        self.assertEqual(vault.load()["refresh_token"], "refresh-2")

    def test_guest_session_persists_and_logout_clears_it(self) -> None:
        vault = MemorySessionVault()
        first = AuthManager(EventBus(), DevelopmentAuthProvider(Path("unused-auth.json")), vault)
        guest = first.guest()
        self.assertEqual(vault.load()["mode"], "guest")

        second = AuthManager(EventBus(), DevelopmentAuthProvider(Path("unused-auth.json")), vault)
        restored = second.restore()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.mode, "guest")
        self.assertEqual(restored.identity.user_id, guest.identity.user_id)
        self.assertTrue(second.logout(restored.token))
        self.assertIsNone(vault.load())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_dpapi_vault_never_writes_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.dpapi"
            vault = WindowsDpapiSessionVault(path)
            vault.save({"refresh_token": "plain-token-must-not-appear"})
            self.assertNotIn(b"plain-token-must-not-appear", path.read_bytes())
            self.assertEqual(vault.load()["refresh_token"], "plain-token-must-not-appear")


if __name__ == "__main__":
    unittest.main()
