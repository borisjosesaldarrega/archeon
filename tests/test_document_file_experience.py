from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from archeon.agent import TaskContext, TaskContextStore
from archeon.documents import DocumentReader, DocumentResolver


class DocumentFileExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_resolver_selects_fuzzy_name_and_refuses_close_ambiguity(self) -> None:
        exact = self.root / "Actividad Optimización Web.docx"
        exact.write_bytes(b"docx")
        resolved = DocumentResolver().resolve(
            "abre mi actividad de optimizacion web", context=TaskContext(), roots=(self.root,),
        )
        self.assertEqual(resolved.status, "selected")
        self.assertEqual(resolved.selected.path, exact.resolve())

        second = self.root / "Actividad Optimización Web (1).docx"
        second.write_bytes(b"docx")
        ambiguous = DocumentResolver().resolve(
            "abre actividad optimizacion web", context=TaskContext(), roots=(self.root,),
        )
        self.assertTrue(ambiguous.ambiguous)
        self.assertGreaterEqual(len(ambiguous.candidates), 2)
        context = TaskContext(recent_entities=[
            {"kind": "document_candidate", "path": str(item.path)} for item in ambiguous.candidates
        ])
        chosen = DocumentResolver().resolve("el segundo", context=context, roots=())
        self.assertEqual(chosen.selected.reason, "disambiguation_choice")
        self.assertEqual(chosen.selected.path, ambiguous.candidates[1].path)

    def test_resolver_uses_yesterday_and_task_context_references(self) -> None:
        yesterday = self.root / "tarea.pdf"
        yesterday.write_bytes(b"pdf")
        stamp = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0).timestamp()
        os.utime(yesterday, (stamp, stamp))
        resolved = DocumentResolver().resolve(
            "busca el pdf que descargué ayer", context=TaskContext(), roots=(self.root,),
        )
        self.assertEqual(resolved.selected.path, yesterday.resolve())
        context = TaskContext(); context.remember_document(str(yesterday), page=2)
        referred = DocumentResolver().resolve("resume ese documento", context=context, roots=())
        self.assertEqual(referred.selected.reason, "task_context")

    def test_large_text_is_read_incrementally_and_bounded(self) -> None:
        source = self.root / "large.txt"
        with source.open("w", encoding="utf-8") as output:
            block = "contenido verificable " * 1000 + "\n"
            for _ in range(150):
                output.write(block)
        reader = DocumentReader()
        content = reader.read(source)
        self.assertLessEqual(len(content.text), reader.MAX_EXTRACTED_CHARACTERS)
        self.assertTrue(content.metadata["extraction_truncated"])
        self.assertGreater(source.stat().st_size, len(content.text.encode("utf-8")))

    def test_task_context_keeps_current_and_previous_document(self) -> None:
        context = TaskContext()
        context.remember_document("C:/one.pdf", page=1)
        context.remember_document("C:/two.docx", page=2)
        self.assertEqual(context.referenced_document(), "C:/two.docx")
        self.assertEqual(context.referenced_document("previous"), "C:/one.pdf")
        self.assertEqual(context.current_page, 2)
        store = TaskContextStore(self.root / "task-context.json")
        store.save(context)
        loaded = store.load()
        self.assertEqual(loaded.referenced_document(), "C:/two.docx")
        self.assertEqual(loaded.referenced_document("previous"), "C:/one.pdf")
        persisted = (self.root / "task-context.json").read_text(encoding="utf-8")
        self.assertNotIn("document body", persisted)


if __name__ == "__main__":
    unittest.main()
