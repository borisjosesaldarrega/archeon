from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from archeon.artifacts import DisabledImageProvider, ImageRequest, LocalImageProvider, ModelResourceManager, StableDiffusionCppImageProvider


PNG_64 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAP0lEQVR4nO3PQQ0AIBDAsAP/nuGNAvZoFSzZOjNnyNi1dgXQBaALQBcALgBdALoAdAHoAtAFoAtAF4AuAF0AugB0AegC0AWgC0AXgC4AXQC6AHQB6ALQBaALQBeALgBdALoAdAHoAtAFoAtAF4AuAF0AuvfAAWlYGbZHAAAAAElFTkSuQmCC")


def test_disabled_provider_is_honest_and_idle(tmp_path: Path) -> None:
    provider = DisabledImageProvider()
    result = provider.generate(ImageRequest("test", tmp_path / "x.png"))
    assert not result.ok and result.error == "archi_image_component_not_installed"
    assert provider.status()["resident"] is False


def test_memory_guard_refuses_pressure_without_loading(tmp_path: Path) -> None:
    manager = ModelResourceManager(tmp_path, minimum_free_bytes=10, memory_reader=lambda: 9)
    assert manager.admit() == (False, "insufficient_available_memory")
    assert manager.loaded is False


def test_local_provider_never_escapes_model_dir_and_is_unavailable(tmp_path: Path) -> None:
    provider = LocalImageProvider(tmp_path)
    assert provider.runtime_path.parent == (tmp_path / "archi-image").resolve()
    result = provider.generate(ImageRequest("diagram", tmp_path / "out.png"))
    assert not result.ok and result.error == "archi_image_runtime_not_installed"
    assert provider.status()["resident"] is False


def test_png_validator_accepts_real_header_and_dimensions(tmp_path: Path) -> None:
    from archeon.artifacts.image_generation import _image_dimensions
    path = tmp_path / "fixture.png"; path.write_bytes(PNG_64)
    assert _image_dimensions(path) == (64, 64)


def test_stable_diffusion_provider_hashes_model_once_per_unchanged_file(tmp_path: Path) -> None:
    model = tmp_path / "model.safetensors"; model.write_bytes(b"model")
    runtime = tmp_path / "sd-cli.exe"; runtime.write_bytes(b"runtime")
    provider = StableDiffusionCppImageProvider(model, cpu_runtime=runtime, backend="cpu", expected_sha256="expected")
    hash_calls = []

    def fake_hash(path: Path) -> str:
        hash_calls.append(path)
        return "expected" if path == model else "output"

    def fake_run(command, **_kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(PNG_64)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with patch("archeon.artifacts.image_generation._sha256", side_effect=fake_hash), patch("archeon.artifacts.image_generation._image_dimensions", return_value=(256, 256)), patch("archeon.artifacts.image_generation.subprocess.run", side_effect=fake_run):
        assert provider.generate(ImageRequest("one", tmp_path / "one.png", 256, 256)).ok
        assert provider.generate(ImageRequest("two", tmp_path / "two.png", 256, 256)).ok
    assert hash_calls.count(model) == 1
    assert provider.status()["resident"] is False


def test_stable_diffusion_provider_rejects_error_log_even_with_zero_exit(tmp_path: Path) -> None:
    model = tmp_path / "model.safetensors"; model.write_bytes(b"model")
    runtime = tmp_path / "sd-cli.exe"; runtime.write_bytes(b"runtime")
    provider = StableDiffusionCppImageProvider(model, cpu_runtime=runtime, backend="cpu")
    with patch("archeon.artifacts.image_generation.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="[ERROR] invalid model", stderr="")):
        result = provider.generate(ImageRequest("test", tmp_path / "bad.png", 256, 256))
    assert not result.ok and result.error == "image_runtime_failed"
    assert not (tmp_path / "bad.png").exists()
