from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from archeon.context import AttachmentStore, FileTypeRouter
from archeon.context.attachments import MAX_ATTACHMENT_BYTES


class AttachmentContextTests(unittest.TestCase):
    def test_streamed_attachment_is_bounded_sanitized_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AttachmentStore(Path(temporary) / "pending")
            body = b"print('archeon')\n" * 80_000

            class ObservedStream(io.BytesIO):
                largest_read = 0

                def read(self, size=-1):
                    self.largest_read = max(self.largest_read, size)
                    return super().read(size)

            source = ObservedStream(body)
            record = store.add_stream("../../main.py", "text/x-python", len(body), source)
            self.assertEqual(record.name, "main.py")
            self.assertEqual(record.kind, "code")
            self.assertEqual(record.public()["extension"], "py")
            self.assertIn("MB", record.public()["size_label"])
            self.assertEqual(FileTypeRouter().route(record).parser, "programming.code")
            self.assertLessEqual(source.largest_read, 1024 * 1024)
            self.assertEqual(record.path.read_bytes(), body)
            self.assertEqual(store.resolve([record.id]), (record,))
            store.release([record.id])
            self.assertFalse(record.path.exists())

    def test_attachment_limits_reject_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AttachmentStore(Path(temporary))
            with self.assertRaisesRegex(ValueError, "attachment_size_out_of_range"):
                store.add_stream("large.bin", "application/octet-stream", MAX_ATTACHMENT_BYTES + 1, io.BytesIO())


if __name__ == "__main__":
    unittest.main()
