from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.auth import AuthManager, DevelopmentAuthProvider
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


if __name__ == "__main__":
    unittest.main()
