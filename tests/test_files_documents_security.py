from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from archeon.artifacts import ArchiveEngineProvider
from archeon.context import AttachmentRecord, FileTypeRouter
from archeon.understanding import NaturalLanguageRepair


class ArchiveIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.project = self.root / "ARCHI_TaskBoard"; self.project.mkdir()
        (self.project / "index.html").write_text("<main>TaskBoard</main>", encoding="utf-8")
        (self.project / "app.js").write_text("localStorage.setItem('tasks','[]')", encoding="utf-8")
        (self.project / "styles.css").write_text("body{color:#fff}", encoding="utf-8")
        self.provider = ArchiveEngineProvider()

    def tearDown(self) -> None: self.temp.cleanup()

    def test_index_tree_compressed_sizes_and_selective_read_without_extract(self) -> None:
        archive = self.root / "taskboard.zip"; created = self.provider.create(archive, [self.project])
        self.assertTrue(created["valid"] and created["safe_to_extract"])
        self.assertIn("ARCHI_TaskBoard", created["tree"]); self.assertEqual(created["risk_counts"]["web_content"], 3)
        member = self.provider.read_member(archive, "ARCHI_TaskBoard/app.js")
        self.assertTrue(member["textual"]); self.assertIn("localStorage", member["text"]); self.assertFalse(member["executed"])
        self.assertFalse(any(path.name.startswith("extract") for path in self.root.iterdir()))

    def test_selective_extract_hashes_only_requested_member(self) -> None:
        archive = self.root / "taskboard.zip"; self.provider.create(archive, [self.project])
        output = self.root / "selected"
        result = self.provider.extract_selected(archive, output, ["ARCHI_TaskBoard/index.html"])
        self.assertTrue(result["verified"] and result["selective"]); self.assertEqual(result["files"], 1)

    def test_duplicate_paths_and_bomb_ratio_are_blocked(self) -> None:
        duplicate = self.root / "duplicate.zip"
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("same.txt", "a"); archive.writestr("same.txt", "b")
        listing = self.provider.list(duplicate); self.assertFalse(listing["safe_to_extract"]); self.assertIn("duplicate_paths", listing["warnings"])
        with self.assertRaisesRegex(ValueError, "archive_security_limits_exceeded"):
            self.provider.extract(duplicate, self.root / "blocked")

        bomb = self.root / "ratio.zip"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive: archive.writestr("zeros.txt", b"0" * 2_000_000)
        self.assertIn("suspicious_compression_ratio", self.provider.list(bomb)["warnings"])

    def test_traversal_and_symlink_are_rejected(self) -> None:
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output: output.writestr("../../escape.txt", "no")
        listing = self.provider.list(archive); self.assertIn("unsafe_path", listing["warnings"])
        with self.assertRaisesRegex(ValueError, "archive_path_traversal_rejected"):
            self.provider.extract(archive, self.root / "blocked")

    def test_router_accepts_all_archive_extensions(self) -> None:
        router = FileTypeRouter()
        for name in ("a.zip", "a.7z", "a.rar", "a.tar", "a.tar.gz"):
            path = self.root / name; path.write_bytes(b"x")
            record = AttachmentRecord("id", name, "application/octet-stream", "archive", 1, path, "0")
            route = router.route(record); self.assertTrue(route.supported, name); self.assertEqual(route.category, "archive")


class NaturalLanguageSecurityTests(unittest.TestCase):
    def test_imperfect_xlsx_and_contextual_csv_json(self) -> None:
        repair = NaturalLanguageRepair()
        first = repair.interpret("hasme un exel con los gastos y una grafica")
        self.assertEqual(first.action, "create"); self.assertIn("xlsx", first.formats)
        second = repair.interpret("ahora pasame esos datos a csv y jason", known_files=("gastos.xlsx",))
        self.assertEqual(second.action, "convert"); self.assertEqual(second.formats, ("csv", "json"))


if __name__ == "__main__": unittest.main()
