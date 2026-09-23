from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine
from archeon.documents import DocumentAgentEngine, DocumentEditor, DocumentReader


FIXTURES = Path(__file__).parent / "fixtures"


class DocumentAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigurationManager(self.root / "config.json")
        self.config.start()
        self.events = EventBus()
        self.tools = ToolEngine(self.events, PermissionEngine(self.config))
        self.agent = DocumentAgentEngine(self.tools)
        self.agent.start()
        self.tools.start()

    def tearDown(self) -> None:
        self.tools.stop()
        self.agent.stop()
        self.events.close()
        self.config.stop()
        self.temp.cleanup()

    @staticmethod
    def context(*permissions: str) -> ToolContext:
        return ToolContext("document-test", scope_permissions=frozenset(permissions))

    def test_text_formats_are_standard_library_only_and_structured(self) -> None:
        sys.modules.pop("pypdf", None)
        sys.modules.pop("docx", None)
        markdown = self.root / "guide.md"
        markdown.write_text("# Title\n\nFind ARCHI here.", encoding="utf-8")
        (self.root / "data.json").write_text(json.dumps({"name": "ARCHI"}), encoding="utf-8")
        (self.root / "data.csv").write_text("name,value\nARCHI,42\n", encoding="utf-8")
        (self.root / "page.html").write_text(
            "<h2>Visible</h2><script>secret()</script><p>ARCHI page</p>", encoding="utf-8",
        )
        reader = DocumentReader()
        md = reader.read(markdown)
        data = reader.read(self.root / "data.json")
        csv = reader.read(self.root / "data.csv")
        html = reader.read(self.root / "page.html")
        self.assertEqual(md.headings[0]["text"], "Title")
        self.assertIn('"name": "ARCHI"', data.text)
        self.assertEqual(csv.tables[0]["rows"], 2)
        self.assertIn("ARCHI page", html.text)
        self.assertNotIn("secret()", html.text)
        self.assertNotIn("pypdf", sys.modules)
        self.assertNotIn("docx", sys.modules)

    def test_pdf_exact_second_page_search_and_visual_fallback_signal(self) -> None:
        reader = DocumentReader()
        second = reader.read(FIXTURES / "document.pdf", page=2)
        found = reader.search(FIXTURES / "document.pdf", "2026-ARC-042")
        self.assertEqual(second.metadata["page_count"], 2)
        self.assertEqual(second.pages[0].number, 2)
        self.assertIn("Boris Saldarrega", second.pages[0].text)
        self.assertEqual(found["matches"][0]["page"], 2)

        from pypdf import PdfWriter

        blank = self.root / "scanned-like.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with blank.open("wb") as stream:
            writer.write(stream)
        no_text = reader.read(blank)
        self.assertTrue(no_text.public()["visual_fallback_required"])
        self.assertFalse(no_text.pages[0].accessible_text)

    def test_docx_reads_structure_and_edits_verified_copy_with_checkpoint(self) -> None:
        source = FIXTURES / "document.docx"
        initial = DocumentReader().read(source)
        self.assertEqual(initial.headings[0]["text"], "ARCHEON Document Fixture")
        self.assertEqual(initial.tables[0]["rows"][1][1], "2026-ARC-042")
        output = self.root / "edited.docx"
        result = DocumentEditor().edit_copy(
            source, output,
            replacements={"Original document paragraph.": "Verified edited paragraph."},
            append_paragraphs=("Appended by ARCHI.",),
        )
        reopened = DocumentReader().read(output)
        self.assertIn("Verified edited paragraph.", reopened.text)
        self.assertIn("Appended by ARCHI.", reopened.text)
        self.assertTrue(Path(result["checkpoint"]).is_file())
        self.assertIn("Original document paragraph.", initial.text)

    def test_permission_gated_tool_reads_only_requested_pdf_page_and_edits_copy(self) -> None:
        denied = self.tools.execute(
            "documents.read", {"path": str(FIXTURES / "document.pdf"), "page": 2},
        )
        read = self.tools.execute(
            "documents.read", {"path": str(FIXTURES / "document.pdf"), "page": 2},
            context=self.context("filesystem.read"),
        )
        output = self.root / "tool-edited.docx"
        edited = self.tools.execute(
            "documents.edit_copy", {
                "source": str(FIXTURES / "document.docx"), "output": str(output),
                "replacements": {"Original document paragraph.": "Tool verified paragraph."},
            }, context=self.context("filesystem.read", "filesystem.write"),
        )
        self.assertFalse(denied.ok)
        self.assertTrue(read.ok and read.verified)
        self.assertEqual(read.data["pages"][0]["number"], 2)
        self.assertEqual(read.evidence["requested_pages"], [2])
        self.assertTrue(edited.ok and edited.verified)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
