from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.core.paths import AppPaths, ResourceManager


class AppPathsTests(unittest.TestCase):
    def test_default_models_are_user_managed_and_not_installed(self) -> None:
        paths = AppPaths.discover(
            package_dir=Path("C:/Program Files/ARCHEON/archeon"),
            executable=Path("C:/Program Files/ARCHEON/Archeo32n.exe"),
            environment={"LOCALAPPDATA": "D:/Users/portable/AppData/Local"},
            frozen=True,
        )
        self.assertEqual(paths.install_dir, Path("C:/Program Files/ARCHEON"))
        self.assertEqual(paths.data_dir, Path("D:/Users/portable/AppData/Local/ARCHEON"))
        self.assertEqual(paths.default_model_dir, paths.data_dir / "models")
        self.assertNotEqual(paths.default_model_dir.parent, paths.install_dir)

    def test_explicit_data_and_model_locations_are_resolved_without_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = AppPaths.discover(
                data_dir=root / "profile",
                package_dir=root / "installed" / "archeon",
                executable=root / "installed" / "Archeo32n.exe",
                environment={},
                frozen=True,
            )
            self.assertEqual(paths.model_dir("models-on-another-disk"), root / "profile" / "models-on-another-disk")
            custom = (root / "external-models").resolve()
            self.assertEqual(paths.model_dir(custom), custom)
            paths.ensure_writable_dirs(custom)
            self.assertTrue(custom.is_dir())
            self.assertTrue(paths.logs_dir.is_dir())
            self.assertTrue(paths.runtimes_dir.is_dir())

    def test_resources_are_confined_to_the_installed_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            package = root / "installed" / "archeon"
            (package / "ui").mkdir(parents=True)
            paths = AppPaths.discover(
                data_dir=root / "profile",
                package_dir=package,
                executable=root / "installed" / "Archeo32n.exe",
                environment={},
                frozen=True,
            )
            resources = ResourceManager(paths)
            self.assertEqual(resources.ui_dir, package / "ui")
            with self.assertRaisesRegex(ValueError, "invalid_resource_path"):
                resources.path("../secret.txt")

    def test_development_asset_fallback_is_relative_to_install_not_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = AppPaths.discover(
                data_dir=root / "profile",
                package_dir=root / "install" / "src" / "archeon",
                executable=root / "python.exe",
                environment={},
                frozen=False,
            )
            self.assertEqual(
                ResourceManager(paths).asset("ARCHEON.mp4"),
                root / "install" / "assets" / "ARCHEON.mp4",
            )


if __name__ == "__main__":
    unittest.main()
