from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from archeon.vision.manager import (
    VisionArtifact, VisionComponentDescriptor, VisionComponentManager, VisionState,
)
from archeon.vision.provider import ArchiVisionProvider
from archeon.vision.engine import _select_control


class VisionManagerTests(unittest.TestCase):
    def test_atomic_install_verifies_hash_and_hides_internal_model_from_public_status(self) -> None:
        body = b"controlled-vision-artifact"
        descriptor = VisionComponentDescriptor(
            "internal-test", "ARCHI Vision", "test", "Apache-2.0", "revision",
            (VisionArtifact("language_model", "model.gguf", "memory://model", len(body), hashlib.sha256(body).hexdigest()),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            manager = VisionComponentManager(Path(temporary))
            result = manager.install_test_component(descriptor, opener=lambda _url: io.BytesIO(body))
            self.assertTrue((manager.component_dir / "model.gguf").is_file())
            self.assertEqual(result["state"], VisionState.UNLOADED.value)
            public = manager.status()
            self.assertNotIn("version", public)
            self.assertNotIn("model_dir", public)

    def test_bad_hash_never_becomes_installed_model(self) -> None:
        body = b"wrong"
        descriptor = VisionComponentDescriptor(
            "internal-test", "ARCHI Vision", "test", "Apache-2.0", "revision",
            (VisionArtifact("language_model", "model.gguf", "memory://model", len(body), "0" * 64),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            manager = VisionComponentManager(Path(temporary))
            with self.assertRaises(ValueError):
                manager.install_test_component(descriptor, opener=lambda _url: io.BytesIO(body))
            self.assertFalse((manager.component_dir / "model.gguf").exists())
            self.assertEqual(manager.state, VisionState.ERROR)

    def test_semantic_contract_rejects_unsafe_grounding_and_normalizes_text(self) -> None:
        self.assertEqual(
            ArchiVisionProvider._text_items("first\nsecond", limit=10, width=100),
            ("first", "second"),
        )
        grounded = ArchiVisionProvider._grounded_items([
            {"name": "safe", "bounds": [0.1, 0.2, 0.8, 0.9]},
            {"name": "native", "bounds": [100, 200, 800, 900]},
            {"name": "unsafe", "bounds": [100, 200, 3000, 4000]},
        ], limit=10)
        self.assertEqual(grounded[0]["bounds"], [0.1, 0.2, 0.8, 0.9])
        self.assertEqual(grounded[1]["bounds"], [0.1, 0.2, 0.8, 0.9])
        self.assertEqual(grounded[1]["grounding_scale"], "normalized_1000")
        self.assertFalse(grounded[2]["grounding_valid"])
        self.assertNotIn("bounds", grounded[2])
        selected = _select_control({"confidence": 0.95, "controls": [grounded[1] | {"label": "OK button"}]}, "OK")
        self.assertEqual(selected["label"], "OK button")


if __name__ == "__main__":
    unittest.main()
