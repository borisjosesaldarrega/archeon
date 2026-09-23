from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.orchestrator import Orchestrator
from archeon.core.permissions import PermissionEngine, PermissionState, RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult
from archeon.database import DatabaseManager
from archeon.system import DeviceSystemEngine


class _ProtectedTool:
    manifest = ToolManifest(
        id="test.protected",
        description="test",
        permissions=("test.permission",),
        risk=RiskLevel.MEDIUM,
    )

    def execute(self, context, arguments):
        return ToolResult(True, {"value": 1})

    def verify(self, context, result):
        return result.data.get("value") == 1


class ToolAndProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.config = ConfigurationManager(Path(self.temp.name) / "config.json")
        self.config.start()
        self.bus = EventBus()
        self.permissions = PermissionEngine(self.config)
        self.tools = ToolEngine(self.bus, self.permissions)

    def tearDown(self) -> None:
        self.tools.stop()
        self.bus.close()
        self.config.stop()
        self.temp.cleanup()

    def test_tool_is_lazy_and_denied_without_confirmation(self) -> None:
        created = 0

        def factory():
            nonlocal created
            created += 1
            return _ProtectedTool()

        self.tools.register(_ProtectedTool.manifest, factory)
        self.tools.start()
        denied = self.tools.execute("test.protected")
        self.assertFalse(denied.ok)
        self.assertEqual(created, 0)
        allowed = self.tools.execute(
            "test.protected",
            context=ToolContext("test", confirmer=lambda request: True),
        )
        self.assertTrue(allowed.ok)
        self.assertTrue(allowed.verified)
        self.assertEqual(created, 1)

    def test_persistent_denial_wins(self) -> None:
        self.permissions.set_state("test.permission", PermissionState.DENIED)
        decision = self.permissions.evaluate(
            ["test.permission"],
            risk=RiskLevel.LOW,
            action="test",
            reason="test",
            confirmer=lambda request: True,
        )
        self.assertFalse(decision.allowed)

    def test_high_level_approval_modes_preserve_risk_boundaries(self) -> None:
        self.config.update_settings({"approval": {"mode": "balanced"}})
        read = self.permissions.evaluate(
            ["filesystem.read"], risk=RiskLevel.READ_ONLY,
            action="read", reason="test",
        )
        write = self.permissions.evaluate(
            ["filesystem.write"], risk=RiskLevel.LOW,
            action="write", reason="test",
        )
        self.assertTrue(read.allowed)
        self.assertFalse(write.allowed)

        self.config.update_settings({"approval": {"mode": "full_control"}})
        control = self.permissions.evaluate(
            ["desktop.control"], risk=RiskLevel.MEDIUM,
            action="control", reason="test",
        )
        critical = self.permissions.evaluate(
            ["account.delete"], risk=RiskLevel.CRITICAL,
            action="delete", reason="test",
        )
        self.assertTrue(control.allowed)
        self.assertFalse(critical.allowed)

        self.permissions.set_state("filesystem.read", PermissionState.DENIED)
        denied = self.permissions.evaluate(
            ["filesystem.read"], risk=RiskLevel.READ_ONLY,
            action="read", reason="test",
        )
        self.assertFalse(denied.allowed)

    def test_real_system_status_and_orchestrator(self) -> None:
        system = DeviceSystemEngine(self.tools)
        system.start()
        self.tools.start()
        orchestrator = Orchestrator(self.bus, self.tools)
        response = orchestrator.handle_text("estado del sistema")
        self.assertTrue(response.ok)
        self.assertGreater(response.data["logical_cpu_count"], 0)
        self.assertGreater(response.data["process"]["working_set_bytes"], 0)
        system.stop()

    def test_orchestrator_responds_in_detected_language(self) -> None:
        system = DeviceSystemEngine(self.tools)
        system.start()
        self.tools.start()
        orchestrator = Orchestrator(self.bus, self.tools)
        response = orchestrator.handle_text("Please show the system status")
        self.assertTrue(response.ok)
        self.assertEqual(response.message, "System status retrieved.")
        system.stop()

    def test_archeon_identity_is_local_deterministic_and_does_not_load_a_model(self) -> None:
        self.tools.start()
        orchestrator = Orchestrator(self.bus, self.tools)
        response = orchestrator.handle_text("¿Quién eres y quién es tu creador?")
        self.assertTrue(response.ok)
        self.assertIn("Boris Saldarrega", response.message)
        self.assertIn("enero de 2020", response.message)
        self.assertEqual(response.data["route"], "local_identity")

    def test_archeon_product_help_knows_settings_without_exposing_internal_paths(self) -> None:
        self.tools.start()
        orchestrator = Orchestrator(self.bus, self.tools)
        response = orchestrator.handle_text("¿Cómo cambio el color y el logo de Archeon?")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["route"], "product_help")
        self.assertEqual(response.data["topic"], "personalization")
        self.assertIn("Personalización", response.message)
        self.assertNotIn("AppData", response.message)
        self.assertNotIn(".gguf", response.message)

    def test_database_provider_stays_unloaded(self) -> None:
        database = DatabaseManager()
        database.start()
        self.assertFalse(database.loaded)
        self.assertEqual(database.health()["provider"], "unloaded")
        database.stop()
        self.assertFalse(database.loaded)


if __name__ == "__main__":
    unittest.main()
