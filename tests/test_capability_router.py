from __future__ import annotations

import unittest

from archeon.agent import Capability, CapabilityRouter
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolManifest


class CapabilityRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CapabilityRouter()

    def test_one_goal_routes_multiple_capabilities_instead_of_one_isolated_intent(self) -> None:
        route = self.router.route(
            "Investiga Docker en la web, crea un informe Word y una hoja Excel, comprímelos en ZIP"
        )
        self.assertIn(Capability.SEARCH, route.capabilities)
        self.assertIn(Capability.BROWSER, route.capabilities)
        self.assertIn(Capability.DOCUMENTS, route.capabilities)
        self.assertIn(Capability.ARTIFACTS, route.capabilities)
        self.assertIn(Capability.ARCHIVES, route.capabilities)
        self.assertIn(Capability.KNOWLEDGE, route.capabilities)
        self.assertTrue(route.source_required and route.control_requested)

    def test_future_cloud_and_extensions_are_contracts_not_implicit_execution(self) -> None:
        route = self.router.route("Sincroniza este plugin .arx con la nube y el móvil")
        self.assertEqual(set(route.future_only), {Capability.CLOUD, Capability.EXTENSIONS})

    def test_tool_selection_only_exposes_registered_tools_for_routed_capabilities(self) -> None:
        route = self.router.route("Crea un PDF y un ZIP")
        manifests = (
            ToolManifest("artifacts.create", "create", ("filesystem.write",), RiskLevel.LOW),
            ToolManifest("archives.create", "archive", ("filesystem.write",), RiskLevel.LOW),
            ToolManifest("terminal.run", "terminal", ("terminal.execute",), RiskLevel.MEDIUM),
        )
        selected = self.router.available_tools(route, manifests)
        self.assertEqual(selected["artifacts"], ["artifacts.create"])
        self.assertEqual(selected["archives"], ["archives.create"])
        self.assertNotIn("terminal", selected)

    def test_attachment_types_add_document_artifact_and_archive_capabilities(self) -> None:
        route = self.router.route("Analiza estos archivos", attachment_names=("report.docx", "data.xlsx", "bundle.7z"))
        self.assertIn(Capability.DOCUMENTS, route.capabilities)
        self.assertIn(Capability.ARTIFACTS, route.capabilities)
        self.assertIn(Capability.ARCHIVES, route.capabilities)


if __name__ == "__main__":
    unittest.main()
