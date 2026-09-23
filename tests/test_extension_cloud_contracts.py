from __future__ import annotations

import json
import hashlib
import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

from archeon.agent import AgentStep, AgentTask, ImprovementCandidate, ImprovementRegistry, TaskStatus, TaskStore
from archeon.cloud import CloudCapability, CloudRequest, UnconfiguredCloudProvider
from archeon.core.events import EventBus
from archeon.plugins import PluginManager
from archeon.plugins import TrustedPublisherVerifier
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ExtensionCloudContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_task_history_and_recovery_keep_current_step_without_private_bodies(self) -> None:
        task = AgentTask("Create artifact", (AgentStep("one", "Create", "artifacts.create"),), ("verified",))
        task.status = TaskStatus.FAILED; task.tool_results.append({"content": "private", "evidence": {"sha256": "abc"}})
        store = TaskStore(self.root / "tasks"); store.save(task)
        history = store.history(); recovered = store.recover(task.id)
        self.assertEqual(history[0]["id"], task.id)
        self.assertTrue(history[0]["recoverable"])
        self.assertEqual(recovered.status, TaskStatus.PLANNING)
        self.assertEqual(recovered.current_step, 0)
        self.assertNotIn("private", (self.root / "tasks" / f"{task.id}.json").read_text(encoding="utf-8"))

    def test_plugin_manifest_has_full_contract_and_unsigned_code_cannot_activate(self) -> None:
        folder = self.root / "plugins" / "demo"; folder.mkdir(parents=True)
        manifest = {
            "id": "demo.plugin", "name": "Demo", "version": "1.0.0", "publisher": "DZKnight",
            "min_archeon_version": "10.0.0", "capabilities": ["artifacts"],
            "permissions": ["filesystem.read"], "entrypoint": "plugin:make", "dependencies": [],
            "hash": "0" * 64, "signature": "declared-but-untrusted", "enabled": True,
        }
        (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        manager = PluginManager(EventBus(), self.root / "plugins"); manager.start()
        try:
            scanned = manager.scan()[0]
            self.assertEqual(scanned.publisher, "DZKnight")
            self.assertEqual(scanned.public()["isolation"], "separate_process")
            self.assertFalse(scanned.signature_verified)
            with self.assertRaisesRegex(PermissionError, "trusted_signature_required"):
                manager.activate("demo.plugin")
        finally:
            manager.stop()

    def test_arx_is_inspected_but_not_installable_without_trusted_signature(self) -> None:
        package = self.root / "demo.arx"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("plugin.json", json.dumps({"id": "demo.plugin", "version": "1", "publisher": "DZKnight", "signature": "sig", "hash": "0" * 64}))
        manager = PluginManager(EventBus(), self.root / "plugins")
        inspected = manager.inspect_arx(package)
        self.assertTrue(inspected["signature_present"])
        self.assertFalse(inspected["signature_verified"])
        self.assertFalse(inspected["installable"])

    def test_arx_rejects_duplicate_paths_before_manifest_or_signature_checks(self) -> None:
        package = self.root / "duplicate.arx"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("plugin.json", "{}")
            archive.writestr("PLUGIN.JSON", "{}")
        manager = PluginManager(EventBus(), self.root / "plugins")
        with self.assertRaisesRegex(ValueError, "arx_duplicate_path_rejected"):
            manager.inspect_arx(package)

    def test_trusted_plugin_install_enable_disable_update_and_remove_lifecycle(self) -> None:
        def package(path: Path, version: str) -> None:
            module = b"class Demo:\n    def start(self): pass\n    def stop(self): pass\ndef make(): return Demo()\n"
            payload = hashlib.sha256()
            payload.update(b"demo_plugin.py\0")
            payload.update(hashlib.sha256(module).digest())
            manifest = {
                "id": "demo.plugin", "name": "Demo", "version": version,
                "publisher": "DZKnight", "min_archeon_version": "10.0.0",
                "capabilities": ["artifacts"], "permissions": ["filesystem.read"],
                "entrypoint": "demo_plugin:make", "dependencies": [],
                "payload_sha256": payload.hexdigest(), "signature": "trusted-test-signature",
                "enabled": False,
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("plugin.json", json.dumps(manifest))
                archive.writestr("demo_plugin.py", module)

        first = self.root / "demo-1.arx"; second = self.root / "demo-2.arx"
        package(first, "1.0.0"); package(second, "1.1.0")
        manager = PluginManager(
            EventBus(), self.root / "plugins",
            signature_verifier=lambda _manifest, signature, publisher: signature == "trusted-test-signature" and publisher == "DZKnight",
            permission_authorizer=lambda _permissions: True,
        )
        manager.start()
        try:
            inspected = manager.inspect_arx(first)
            self.assertTrue(inspected["installable"] and inspected["payload_verified"])
            self.assertEqual(manager.install(first).version, "1.0.0")
            manager.enable("demo.plugin")
            self.assertEqual(manager.loaded_count, 1)
            self.assertFalse(any((self.root / "plugins" / "demo.plugin").rglob("*.pyc")))
            manager.stop()
            manager = PluginManager(
                EventBus(), self.root / "plugins",
                signature_verifier=lambda _manifest, signature, publisher: signature == "trusted-test-signature" and publisher == "DZKnight",
                permission_authorizer=lambda _permissions: True,
            )
            manager.start()
            self.assertEqual(manager.loaded_count, 1)
            manager.disable("demo.plugin")
            self.assertEqual(manager.loaded_count, 0)
            self.assertEqual(manager.update(second).version, "1.1.0")
            self.assertTrue(manager.remove("demo.plugin"))
            self.assertFalse(manager.remove("demo.plugin"))
        finally:
            manager.stop()

    def test_ed25519_publisher_trust_root_verifies_and_rejects_tampering(self) -> None:
        trust = self.root / "trust"; trust.mkdir()
        private_key = Ed25519PrivateKey.generate()
        (trust / "DZKnight.pem").write_bytes(private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        verifier = TrustedPublisherVerifier(trust)
        payload = b"canonical manifest"
        signature = base64.b64encode(private_key.sign(payload)).decode("ascii")
        self.assertTrue(verifier.configured)
        self.assertTrue(verifier(payload, signature, "DZKnight"))
        self.assertFalse(verifier(payload + b"!", signature, "DZKnight"))
        self.assertFalse(verifier(payload, signature, "unknown/publisher"))

    def test_plugin_permissions_are_known_and_explicitly_granted(self) -> None:
        folder = self.root / "plugins" / "demo"; folder.mkdir(parents=True)
        module = b"def make(): return object()\n"
        payload = hashlib.sha256(); payload.update(b"demo.py\0"); payload.update(hashlib.sha256(module).digest())
        manifest = {
            "id": "demo.plugin", "version": "1.0.0", "publisher": "DZKnight",
            "entrypoint": "demo:make", "payload_sha256": payload.hexdigest(),
            "signature": "trusted", "permissions": ["filesystem.read"],
        }
        (folder / "demo.py").write_bytes(module)
        (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        manager = PluginManager(EventBus(), self.root / "plugins", signature_verifier=lambda *_: True)
        manager.scan()
        with self.assertRaisesRegex(PermissionError, "plugin_permissions_not_granted"):
            manager.activate("demo.plugin")
        manifest["permissions"] = ["unknown.permission"]
        (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(manager.scan(), ())

    def test_future_cloud_contract_requires_identity_consent_and_has_no_fake_backend(self) -> None:
        request = CloudRequest(CloudCapability.ARTIFACT_SYNC, "user-1", {"artifact": "x"}, "consent")
        with self.assertRaisesRegex(PermissionError, "authenticated_cloud_identity_required"):
            request.validate(authenticated_identity=None)
        request.validate(authenticated_identity="user-1")
        self.assertEqual(request.public()["consent_token"], "<redacted>")
        with self.assertRaisesRegex(RuntimeError, "not_implemented"):
            UnconfiguredCloudProvider().execute(request)

    def test_improvement_candidate_is_evidence_only_and_never_auto_applied(self) -> None:
        registry = ImprovementRegistry(self.root / "improvements.json")
        candidate = ImprovementCandidate(
            "Reduce browser latency", "reload is slow", ({"benchmark_ms": 1200},),
            "Cache validators", ("run regression", "compare p95"), "low",
        )
        registry.record(candidate)
        stored = registry.list()[0]
        self.assertTrue(stored["approval_required"])
        self.assertFalse(stored["applied"])


if __name__ == "__main__":
    unittest.main()
