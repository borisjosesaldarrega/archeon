from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.artifacts import ArtifactProvider, ArtifactSpec
from archeon.artifacts.engine import ArtifactEngine
from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine


class ArtifactProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.provider = ArtifactProvider()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def spec(self, name: str, **values: object) -> ArtifactSpec:
        return ArtifactSpec.from_mapping({"path": str(self.root / name), **values})

    def test_create_and_reopen_all_required_artifact_formats(self) -> None:
        specs = [
            self.spec("report.docx", title="Docker Research", content="Container summary", sections=[{"heading": "Sources", "body": "Official documentation"}]),
            self.spec("budget.xlsx", title="Budget", sheets=[{"name": "Totals", "rows": [["Item", "Amount"], ["A", 10], ["B", 20]], "formulas": {"B4": "=SUM(B2:B3)"}, "chart": {"title": "Totals"}}]),
            self.spec("brief.pptx", title="ARCHEON", slides=[{"title": f"Slide {index}", "body": f"Content {index}"} for index in range(1, 7)]),
            self.spec("summary.pdf", title="Summary", content="Verified PDF content"),
            self.spec("notes.txt", content="plain text"), self.spec("readme.md", content="# Markdown"),
            self.spec("data.csv", rows=[["name", "value"], ["archi", 1]]),
            self.spec("data.json", metadata={"data": {"archi": True}}),
            self.spec("page.html", title="Page", content="Accessible content"),
        ]
        results = {spec.format: self.provider.create(spec) for spec in specs}
        self.assertTrue(all(item.verified for item in results.values()))
        self.assertEqual(results["pptx"].structure["slides"], 6)
        self.assertEqual(results["xlsx"].structure["charts"], 1)
        self.assertIn("Verified PDF", results["pdf"].structure["text"])

    def test_edit_copy_checkpoints_and_reopens_docx_xlsx_pptx_pdf(self) -> None:
        docx = self.provider.create(self.spec("source.docx", title="Original", content="alpha"))
        xlsx = self.provider.create(self.spec("source.xlsx", sheets=[{"name": "Data", "rows": [["Name", "Value"], ["A", 1]]}]))
        pptx = self.provider.create(self.spec("source.pptx", slides=[{"title": "Original", "body": "alpha"}]))
        pdf = self.provider.create(self.spec("source.pdf", title="Original", content="alpha"))
        edited_docx = self.provider.edit_copy(docx.path, self.root / "edited.docx", replacements={"alpha": "beta"}, append="Appendix")
        edited_xlsx = self.provider.edit_copy(xlsx.path, self.root / "edited.xlsx", cell_updates={"Data!B2": 2})
        edited_pptx = self.provider.edit_copy(pptx.path, self.root / "edited.pptx", replacements={"alpha": "beta"}, append="Appendix")
        edited_pdf = self.provider.edit_copy(pdf.path, self.root / "edited.pdf", append="Appendix")
        for result in (edited_docx, edited_xlsx, edited_pptx, edited_pdf):
            self.assertTrue(result.verified)
            self.assertTrue(Path(result.checkpoint).is_file())
        self.assertEqual(edited_pdf.structure["pages"], 2)
        self.assertEqual(edited_pptx.structure["slides"], 2)

    def test_complete_html_document_is_not_escaped_and_local_resources_are_verified(self) -> None:
        self.provider.create(self.spec("styles.css", content=".cards{display:grid}@media(max-width:700px){.cards{display:block}}"))
        self.provider.create(self.spec("script.js", content='document.querySelector("button").addEventListener("click",()=>{});'))
        source = '<!doctype html><html lang="es"><head><link rel="stylesheet" href="styles.css"></head><body><button>Probar</button><script src="script.js"></script></body></html>'
        result = self.provider.create(self.spec("index.html", content=source))
        self.assertTrue(result.verified)
        self.assertEqual((self.root / "index.html").read_text(encoding="utf-8"), source)
        self.assertEqual(result.structure["references"], ["styles.css", "script.js"])

    def test_tool_engine_permissions_and_verification(self) -> None:
        config = ConfigurationManager(self.root / "config.json"); config.start()
        events = EventBus(); tools = ToolEngine(events, PermissionEngine(config)); artifacts = ArtifactEngine(tools)
        artifacts.start(); tools.start()
        try:
            denied = tools.execute("artifacts.create", {"path": str(self.root / "denied.txt"), "content": "no"})
            allowed = tools.execute(
                "artifacts.create", {"path": str(self.root / "allowed.json"), "metadata": {"data": {"ok": True}}},
                context=ToolContext("artifact", scope_permissions=frozenset({"filesystem.write"})),
            )
            verified = tools.execute(
                "artifacts.verify", {"path": str(self.root / "allowed.json")},
                context=ToolContext("artifact", scope_permissions=frozenset({"filesystem.read"})),
            )
            self.assertFalse(denied.ok)
            self.assertTrue(allowed.verified and verified.verified)
        finally:
            tools.stop(); artifacts.stop(); events.close(); config.stop()


if __name__ == "__main__":
    unittest.main()
