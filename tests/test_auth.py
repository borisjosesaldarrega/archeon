from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from archeon.auth import AuthManager, DevelopmentAuthProvider, MemorySessionVault, WindowsDpapiSessionVault
from archeon.auth.manager import Identity, ProviderSession
from archeon.core.events import EventBus


class AuthTests(unittest.TestCase):
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
