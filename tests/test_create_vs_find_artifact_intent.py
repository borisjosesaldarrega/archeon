from __future__ import annotations

import tempfile
import unittest
import re
from unittest.mock import patch
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.artifacts import ImageResult
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault


class _FakeArchiImageProvider:
    def status(self) -> dict[str, object]:
        return {"name": "ARCHI Image Test", "state": "unloaded", "implemented": True, "resident": False}

    def generate(self, request) -> ImageResult:
        from PIL import Image

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        color = (32 + (request.seed or 0) % 160, 92, 128)
        Image.new("RGB", (request.width, request.height), color).save(request.output_path, "PNG")
        return ImageResult(
            True, "ARCHI Image Test", "unloaded", str(request.output_path),
            request.width, request.height, "test-sha256", 1.0,
        )

    def unload(self) -> None:
        return None


class CreateVsFindArtifactIntentRegressionTests(unittest.TestCase):
    """Creation verbs govern routing; format nouns never imply resolution."""

    def test_create_variants_never_route_to_document_resolver(self) -> None:
        variants = (
            "crea un documento Word",
            "hazme un PDF nuevo",
            "genera una presentación",
            "crea una web",
            "crea un archivo Python",
        )
        for phrase in variants:
            with self.subTest(phrase=phrase):
                self.assertEqual(ArcheonApplication._artifact_intent(phrase), "CREATE_ARTIFACT")

    def test_find_open_modify_variants_remain_document_operations(self) -> None:
        for phrase in ("busca el documento Word", "abre el PDF", "modifica este archivo", "edita la presentación", "continúa este documento"):
            with self.subTest(phrase=phrase):
                self.assertEqual(ArcheonApplication._artifact_intent(phrase), "FIND_OPEN_MODIFY_ARTIFACT")

    def test_creation_words_in_narration_questions_or_negation_do_not_execute(self) -> None:
        variants = (
            "El profesor dijo que cree un PDF para mañana",
            "Quiero aprender a crear una web",
            "¿Cómo creo un documento Word?",
            "No crees un PDF",
            "Si creo un archivo Python, ¿dónde se guarda?",
            'La frase "crea una presentación" es un ejemplo',
        )
        for phrase in variants:
            with self.subTest(phrase=phrase):
                self.assertIsNone(ArcheonApplication._artifact_intent(phrase))

    def test_polite_direct_creation_requests_still_execute(self) -> None:
        variants = (
            "ARCHI, crea un documento Word",
            "Por favor, hazme un PDF nuevo",
            "¿Puedes generar una presentación?",
            "Necesito que diseñes una web",
        )
        for phrase in variants:
            with self.subTest(phrase=phrase):
                self.assertEqual(ArcheonApplication._artifact_intent(phrase), "CREATE_ARTIFACT")

    def test_powerpoint_support_images_do_not_create_an_unrequested_png(self) -> None:
        phrase = "ARCHI, crea una presentación PowerPoint con imágenes creadas por ti"
        normalized = " ".join(phrase.casefold().split())
        self.assertEqual(ArcheonApplication._artifact_intent(phrase), "CREATE_ARTIFACT")
        self.assertEqual(ArcheonApplication._requested_artifact_formats(normalized), ("pptx",))
        self.assertEqual(
            set(ArcheonApplication._requested_artifact_formats("crea un powerpoint y una imagen por separado")),
            {"pptx", "png"},
        )

    def test_single_powerpoint_request_uses_generated_images_without_extra_png(self) -> None:
        phrase = "ARCHI, crea una presentación PowerPoint con imágenes creadas por ti"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = ArcheonApplication(
                data_dir=root / "data", port=0, image_provider=_FakeArchiImageProvider(),
                auth_provider=DevelopmentAuthProvider(root / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                response = application.handle_command(phrase)
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["data"]["intent"], "CREATE_ARTIFACT")
            self.assertEqual(len(response["data"]["artifacts"]), 1)
            powerpoint = response["data"]["artifacts"][0]
            self.assertEqual(powerpoint["format"], "pptx")
            self.assertEqual(powerpoint["visuals"]["generated"], 5)
            self.assertEqual(powerpoint["visuals"]["embedded"], 5)

    def test_real_create_command_returns_physical_artifact_not_resolver_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            application = ArcheonApplication(
                data_dir=data, port=0,
                auth_provider=DevelopmentAuthProvider(data / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                response = application.handle_command("crea un archivo Python")
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["data"]["intent"], "CREATE_ARTIFACT")
            self.assertEqual(response["data"]["route"], "project_creation")
            self.assertNotEqual(response["data"]["route"], "document_resolver")
            created = Path(response["data"]["artifacts"][0]["path"])
            self.assertTrue(created.is_file())
            self.assertEqual(created.suffix, ".py")

    def test_complete_multi_artifact_plan_creates_and_verifies_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            downloads = Path(directory) / "Downloads"
            downloads.mkdir()
            application = ArcheonApplication(
                data_dir=data, port=0,
                auth_provider=DevelopmentAuthProvider(data / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                response = application._create_autonomous_education_bundle(
                    "Crea Word, PDF, PNG, PPTX, Python, web y ZIP",
                    downloads_root=downloads,
                )
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["data"]["intent"], "CREATE_MULTI_ARTIFACT")
            self.assertFalse(response["data"]["user_verified"])
            self.assertEqual(response["data"]["failures"], [])
            self.assertTrue(Path(response["data"]["archive"]).is_file())
            self.assertTrue(all(item["exists"] and item["verified"] for item in response["data"]["artifacts"]))

    def test_generic_word_and_powerpoint_request_keeps_folder_and_slide_count(self) -> None:
        prompt = (
            "ARCHI, hazme un trabajo en Word de dos páginas sobre la contaminación ambiental, "
            "con portada sencilla, introducción, causas, consecuencias y soluciones. Después crea "
            "una presentación de 5 diapositivas basada en el trabajo. Guarda ambos archivos en "
            "Descargas dentro de una carpeta llamada Prueba Final."
        )
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            downloads = Path(directory) / "Downloads"
            downloads.mkdir()
            application = ArcheonApplication(
                data_dir=data, port=0,
                auth_provider=DevelopmentAuthProvider(data / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                response = application._create_generic_multi_artifact_project(
                    prompt, " ".join(prompt.casefold().split()), downloads_root=downloads,
                )
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(Path(response["data"]["workspace"]).name, "Prueba Final")
            self.assertEqual({item["format"] for item in response["data"]["artifacts"]}, {"docx", "pptx"})
            self.assertTrue(all(item["exists"] and item["verified"] for item in response["data"]["artifacts"]))
            pptx = next(Path(item["path"]) for item in response["data"]["artifacts"] if item["format"] == "pptx")
            import zipfile
            with zipfile.ZipFile(pptx) as archive:
                slides = [name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            self.assertEqual(len(slides), 5)

    def test_screenshot_prompt_routes_end_to_end_without_losing_second_artifact(self) -> None:
        prompt = (
            "ARCHI, hazme un trabajo en Word de dos páginas sobre la contaminación ambiental, "
            "con portada sencilla, introducción, causas, consecuencias y soluciones. Después crea "
            "una presentación de 5 diapositivas basada en el trabajo. Guarda ambos archivos en "
            "Descargas dentro de una carpeta llamada Prueba Final."
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "Downloads"
            downloads.mkdir()
            application = ArcheonApplication(
                data_dir=root / "data", port=0,
                auth_provider=DevelopmentAuthProvider(root / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                with patch("archeon.app.Path.home", return_value=root):
                    response = application.handle_command(prompt)
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["data"]["route"], "project_creation")
            self.assertEqual(response["data"]["intent"], "CREATE_MULTI_ARTIFACT")
            self.assertEqual(Path(response["data"]["workspace"]), downloads / "Prueba Final")
            self.assertEqual(len(response["data"]["artifacts"]), 2)

    def test_powerpoint_uses_distinct_archi_images_and_verifies_embedding(self) -> None:
        prompt = (
            "ARCHI, hazme un trabajo en Word de dos páginas sobre la contaminación ambiental. "
            "Después crea una presentación de 5 diapositivas basada en el trabajo con imágenes. "
            "Guarda ambos archivos en Descargas dentro de una carpeta llamada Prueba Visual."
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "Downloads"; downloads.mkdir()
            application = ArcheonApplication(
                data_dir=root / "data", port=0, image_provider=_FakeArchiImageProvider(),
                auth_provider=DevelopmentAuthProvider(root / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                response = application._create_generic_multi_artifact_project(
                    prompt, " ".join(prompt.casefold().split()), downloads_root=downloads,
                )
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            powerpoint = next(item for item in response["data"]["artifacts"] if item["format"] == "pptx")
            self.assertEqual(powerpoint["visuals"]["generated"], 5)
            self.assertEqual(powerpoint["visuals"]["embedded"], 5)
            self.assertTrue(all(
                Path(item["path"]).parent.name == "Recursos visuales"
                for item in powerpoint["visuals"]["images"]
            ))
            import zipfile
            with zipfile.ZipFile(powerpoint["path"]) as archive:
                media = [name for name in archive.namelist() if name.startswith("ppt/media/")]
            self.assertEqual(len(media), 5)

    def test_standalone_archi_image_is_saved_to_downloads_and_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "Downloads"; downloads.mkdir()
            application = ArcheonApplication(
                data_dir=root / "data", port=0, image_provider=_FakeArchiImageProvider(),
                auth_provider=DevelopmentAuthProvider(root / "auth.json"),
                auth_vault=MemorySessionVault(),
            )
            application.start()
            try:
                with patch("archeon.app.Path.home", return_value=root):
                    response = application.handle_command(
                        "ARCHI, hazme una imagen de un bosque al amanecer y guárdala en "
                        "Descargas dentro de una carpeta llamada Imagen Prueba con el nombre bosque.png"
                    )
            finally:
                application.stop()
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["data"]["route"], "archi_image")
            artifact = response["data"]["artifacts"][0]
            self.assertTrue(artifact["ok"] and artifact["verified"])
            self.assertEqual(
                str(Path(artifact["path"])).casefold(),
                str(downloads / "Imagen Prueba" / "bosque.png").casefold(),
            )
            self.assertEqual(artifact["prompt"], "un bosque al amanecer")

    def test_obvious_split_scene_image_is_rejected_before_embedding(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.png"
            image = Image.new("RGB", (768, 512), "#18384d")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 190, 767, 205), fill="white")
            draw.rectangle((0, 365, 767, 380), fill="white")
            image.save(path)
            self.assertTrue(ArcheonApplication._presentation_image_has_split_seams(path))


if __name__ == "__main__":
    unittest.main()
