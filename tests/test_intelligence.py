from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.intelligence import GenerationRequest, GenerationResult, LlamaCppProvider, ModelManager, ModelRouter, ModelState, RouteDecision
from archeon.intelligence.models import ModelDescriptor, ModelRegistry


DESCRIPTOR = ModelDescriptor(
    id="reference", family="qwen3", filename="reference.gguf", quantization="Q4_K_M",
    size_bytes=4, sha256="0" * 64, source="https://example.test/model", license="Apache-2.0", version="main",
)


class FakeProvider:
    def __init__(self) -> None:
        self.state = ModelState.UNLOADED
        self.unloads = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.state = ModelState.READY
        return GenerationResult("Soy local.", "reference", 2, 3, 10, None, 20)

    def unload(self) -> None:
        self.unloads += 1
        self.state = ModelState.UNLOADED

    def status(self):
        return {"state": self.state.value, "model_id": "reference"}


class IntelligenceTests(unittest.TestCase):
    def test_registry_is_provider_neutral_and_confines_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ModelRegistry(Path(directory))
            registry.register(DESCRIPTOR)
            self.assertEqual(registry.get("reference"), DESCRIPTOR)
            self.assertEqual(registry.model_path(DESCRIPTOR), Path(directory) / "reference.gguf")

    def test_router_keeps_deterministic_tools_out_of_model(self) -> None:
        router = ModelRouter()
        self.assertEqual(router.route("estado del sistema").decision, RouteDecision.TOOL)
        self.assertEqual(router.route("Explícame qué es una API").decision, RouteDecision.LOCAL_AI)

    def test_manager_does_not_load_provider_when_started(self) -> None:
        provider = FakeProvider()
        manager = ModelManager(provider)
        manager.start()
        self.assertEqual(provider.state, ModelState.UNLOADED)
        result = manager.generate(GenerationRequest(({"role": "user", "content": "hola"},)))
        self.assertEqual(result.text, "Soy local.")
        manager.stop()
        self.assertEqual(provider.unloads, 1)

    def test_generation_result_keeps_stage_timings_separate_from_visible_text(self) -> None:
        result = GenerationResult("Respuesta", "reference", 2, 3, 0, 100, 200, {"http_wait_ms": 25})
        self.assertEqual(result.text, "Respuesta")
        self.assertEqual(result.timings["http_wait_ms"], 25)

    def test_generation_request_accepts_a_non_serialized_stream_callback(self) -> None:
        parts = []
        request = GenerationRequest(({"role": "user", "content": "hola"},), on_token=parts.append)
        self.assertNotIn("on_token", repr(request))
        request.on_token("respuesta")
        self.assertEqual(parts, ["respuesta"])

    def test_verified_model_receipt_avoids_rehash_until_file_changes(self) -> None:
        import hashlib
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "reference.gguf"
            model_path.write_bytes(b"test")
            stat = model_path.stat()
            descriptor = ModelDescriptor(
                id="reference", family="qwen3", filename=model_path.name, quantization="Q4_K_M",
                size_bytes=4, sha256=hashlib.sha256(b"test").hexdigest(), source="official",
                license="Apache-2.0", version="test",
            )
            receipt = model_path.with_name(f".{model_path.name}.verified.json")
            receipt.write_text(json.dumps({
                "schema_version": 1, "sha256": descriptor.sha256,
                "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            }), encoding="utf-8")
            provider = LlamaCppProvider(root / "missing-server.exe", model_path, descriptor)
            provider._verify_model()
            self.assertTrue(provider._integrity_verified)
