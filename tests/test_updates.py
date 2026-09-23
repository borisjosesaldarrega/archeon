from pathlib import Path
from tempfile import TemporaryDirectory

from archeon.updates import ReleaseInfo, UpdateManager


class FakeProvider:
    name = "signed-test"
    configured = True

    def check(self, current_version: str):
        return ReleaseInfo("10.0.1", "Fixes", "https://example.test/update", "a" * 64, "signature")

    def download(self, release, destination):
        return destination


def test_unconfigured_update_provider_is_explicit():
    result = UpdateManager("10.0.0").check()
    assert result["ok"] is False
    assert result["error"] == "update_backend_not_configured"


def test_verified_update_contract_requires_hash_and_signature():
    manager = UpdateManager("10.0.0", FakeProvider())
    assert manager.check()["status"]["available_version"] == "10.0.1"
    with TemporaryDirectory() as value:
        package = Path(value) / "update.exe"
        package.write_bytes(b"fixture")
        manager.mark_verified_download(package, sha256_verified=True, signature_verified=True)
    assert manager.status()["install_state"] == "ready_to_install"
