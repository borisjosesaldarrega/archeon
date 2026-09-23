from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archeon.agent import TaskContext, TaskContextStore
from archeon.artifacts import ArtifactProvider, ArtifactSpec
from archeon.documents import DocumentStyleProfile, EvidenceCapture, RequirementChecker, write_evidence_manifest
from archeon.understanding import Confidence, NaturalLanguageRepair, QualityProfile, WritingStyle, WritingStyleEngine
from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault


class NaturalLanguageFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repair = NaturalLanguageRepair()

    def test_imperfect_academic_request_preserves_raw_and_recovers_intent(self) -> None:
        raw = "has el trabajo con las cap que tomaste y no tan ia"
        result = self.repair.interpret(raw)
        self.assertEqual(result.raw_user_input, raw)
        self.assertEqual(result.action, "create")
        self.assertTrue(result.include_evidence)
        self.assertEqual(result.writing_style, "student")
        self.assertIn("capturas", result.repaired_text)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_voice_phonetics_resolve_word_and_pdf(self) -> None:
        result = self.repair.interpret("Archeon has el deber en wor y después pe de efe", stt_confidence=.82)
        self.assertEqual(result.formats, ("docx", "pdf"))
        self.assertFalse(result.clarification_required)

    def test_excel_to_pdf_uses_active_context(self) -> None:
        context = TaskContext(selected_file="C:/Downloads/datos.xlsx")
        result = self.repair.interpret("pasame el exel a pef", context=context)
        self.assertEqual(result.action, "convert")
        self.assertEqual(result.formats, ("pdf",))
        self.assertIn("active_document:xlsx", result.reasons)

    def test_ambiguous_delete_never_executes_by_approximation(self) -> None:
        result = self.repair.interpret("borra el archivo ese")
        self.assertEqual(result.confidence, Confidence.LOW)
        self.assertTrue(result.clarification_required)

    def test_responsive_photo_reference_is_resolved(self) -> None:
        result = self.repair.interpret("la foto de abajo ponla despues de donde ablas del responsive")
        self.assertEqual(result.action, "edit")
        self.assertEqual(result.reference, "responsive")


class WritingAndStyleTests(unittest.TestCase):
    def test_no_tan_ia_is_style_not_detector_evasion(self) -> None:
        profile = WritingStyleEngine().resolve("ponlo como estudiante, no tan IA")
        self.assertEqual(profile.style, WritingStyle.STUDENT)
        prompt = WritingStyleEngine.prompt(profile)
        self.assertIn("No introduzcas errores intencionales", prompt)

    def test_thorough_quality_and_local_preference_threshold(self) -> None:
        context = TaskContext(); context.remember_writing_feedback("concise")
        self.assertFalse(context.learned_writing_preferences()["concise"])
        context.remember_writing_feedback("concise")
        self.assertTrue(context.learned_writing_preferences()["concise"])
        profile = WritingStyleEngine().resolve("revísalo bien", learned=context.learned_writing_preferences())
        self.assertEqual(profile.quality, QualityProfile.THOROUGH)
        self.assertTrue(profile.concise)

    def test_document_property_language_maps_to_real_profile(self) -> None:
        profile = DocumentStyleProfile.interpret(
            "hazlo horizontal con margen estrecho, letra Arial 11, títulos morados e interlineado 1.5"
        )
        self.assertEqual(profile.orientation, "landscape")
        self.assertEqual(profile.margin, "narrow")
        self.assertEqual(profile.font_family, "Arial")
        self.assertEqual(profile.font_size, 11)
        self.assertEqual(profile.heading_color, "7030A0")
        self.assertEqual(profile.line_spacing, 1.5)

    def test_task_context_persists_only_bounded_style_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskContextStore(Path(temporary) / "context.json")
            context = TaskContext(); context.remember_writing_feedback("less_formal"); store.save(context)
            self.assertEqual(store.load().writing_feedback["less_formal"], 1)


class ArtifactQualityFoundationTests(unittest.TestCase):
    def test_docx_properties_and_final_requirement_counts(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); target = root / "styled.docx"
            provider = ArtifactProvider()
            provider.create(ArtifactSpec.from_mapping({
                "path": str(target), "title": "Actividad web", "content": "Texto natural.",
                "sections": [{"heading": "Hallazgos", "rows": [["Hallazgo", "Tipo"], ["Navegación clara", "Fortaleza"]]}],
                "metadata": {"style_profile": DocumentStyleProfile.interpret("Arial 11 títulos morados").public()},
            }))
            reopened = Document(target)
            self.assertEqual(reopened.styles["Normal"].font.name, "Arial")
            self.assertEqual(str(reopened.styles["Heading 1"].font.color.rgb), "7030A0")
            checks = RequirementChecker().check_docx(target, [
                {"requirement": "Hallazgos", "pattern": r"Hallazgos"},
                {"requirement": "Una fila", "table_rows": 1},
            ])
            self.assertTrue(all(item.status == "PASS" for item in checks))

    def test_evidence_manifest_checks_real_file_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            from PIL import Image
            root = Path(temporary); image = root / "evidence.png"
            Image.new("RGB", (120, 80), "white").save(image)
            capture = EvidenceCapture.from_file(
                image, source="browser", task_step="home", target="python.org",
                caption="Figura 1. Vista inicial.", url="https://www.python.org/", viewport="1280x800",
            )
            manifest = write_evidence_manifest(root / "manifest.json", [capture])
            self.assertTrue(manifest.is_file())
            image.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "digest"):
                write_evidence_manifest(root / "second.json", [capture])


class ApplicationLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(); root = Path(self.temporary.name)
        self.application = ArcheonApplication(
            data_dir=root, port=0,
            auth_provider=DevelopmentAuthProvider(root / "auth.json"),
            auth_vault=MemorySessionVault(),
        )
        self.application.start()

    def tearDown(self) -> None:
        self.application.stop(); self.temporary.cleanup()

    def test_application_exposes_raw_input_and_separate_interpretation(self) -> None:
        raw = "que dia es oi"
        response = self.application.handle_command(raw)
        self.assertEqual(response["data"]["raw_user_input"], raw)
        self.assertEqual(response["data"]["interpreted_intent"]["raw_user_input"], raw)

    def test_ambiguous_destructive_language_stops_before_any_action(self) -> None:
        response = self.application.handle_command("borra el archivo ese")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "natural_language_clarification")

    def test_artifact_open_is_limited_to_task_context(self) -> None:
        target = Path(self.temporary.name) / "result.txt"; target.write_text("ok", encoding="utf-8")
        denied = self.application.handle_action("artifact.open", {"path": str(target)})
        self.assertFalse(denied["ok"])
        self.application._task_context.remember_document(str(target), source="test")
        with patch("archeon.app.os.startfile") as startfile:
            allowed = self.application.handle_action("artifact.open", {"path": str(target)})
        self.assertTrue(allowed["ok"]); startfile.assert_called_once_with(str(target.resolve()))


if __name__ == "__main__":
    unittest.main()
