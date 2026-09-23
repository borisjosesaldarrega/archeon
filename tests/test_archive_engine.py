from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from archeon.artifacts import ArchiveEngineProvider


class ArchiveEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / "source"; self.source.mkdir()
        (self.source / "alpha.txt").write_text("alpha", encoding="utf-8")
        (self.source / "nested").mkdir(); (self.source / "nested" / "beta.json").write_text('{"beta": true}', encoding="utf-8")
        self.provider = ArchiveEngineProvider()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_zip_tar_and_tar_gz_create_verify_list_and_extract(self) -> None:
        for name in ("bundle.zip", "bundle.tar", "bundle.tar.gz"):
            created = self.provider.create(self.root / name, [self.source])
            self.assertTrue(created["valid"])
            self.assertEqual(created["member_count"], 2 if name.endswith("zip") else 4)
            extracted = self.provider.extract(self.root / name, self.root / f"extract-{name.replace('.', '-')}")
            self.assertTrue(extracted["verified"])
            self.assertEqual(extracted["files"], 2)

    def test_path_traversal_is_rejected_before_destination_exists(self) -> None:
        malicious = self.root / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape.txt", "blocked")
        destination = self.root / "blocked-extraction"
        with self.assertRaisesRegex(ValueError, "archive_path_traversal_rejected"):
            self.provider.extract(malicious, destination)
        self.assertFalse(destination.exists())
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_7z_and_rar_are_explicit_optional_unbundled_providers(self) -> None:
        capabilities = self.provider.capabilities()
        self.assertFalse(capabilities["7z"]["bundled"])
        self.assertFalse(capabilities["rar"]["bundled"])
        self.assertTrue(capabilities["rar"]["licensed_provider_required"])
        if not capabilities["7z"]["available"]:
            with self.assertRaisesRegex(RuntimeError, "optional_provider_unavailable"):
                self.provider.create(self.root / "bundle.7z", [self.source])


if __name__ == "__main__":
    unittest.main()
