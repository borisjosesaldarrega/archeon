from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from archeon.core.config import SUPPORTED_LOCALES
from archeon.core.language import LanguageContextEngine, LOCALE_SPECS, locale_direction
from archeon.core.messages import core_message, identity_message, product_help_message, response_directive
from archeon.core.multilingual import LANGUAGE_PROBES, MultilingualQualityGate
from archeon.intelligence.router import ModelRouter, RouteDecision
from archeon.documents import DocumentStyleProfile
from archeon.media.matcher import MediaSearchQuery, normalize as normalize_media
from archeon.understanding import NaturalLanguageRepair
from archeon.ui.server import UI_ROOT


class MultilingualQualityTests(unittest.TestCase):
    def test_language_detection_covers_all_twelve_locales(self) -> None:
        engine = LanguageContextEngine()
        self.assertEqual(tuple(LANGUAGE_PROBES), SUPPORTED_LOCALES)
        for locale, probe in LANGUAGE_PROBES.items():
            with self.subTest(locale=locale):
                self.assertEqual(engine.detect(probe), locale)

    def test_conversation_can_switch_es_en_pt_ar_without_losing_selected_language(self) -> None:
        engine = LanguageContextEngine()
        turns = (
            ("Explícame DNS en español", "es"),
            ("Now summarize that in English", "en"),
            ("Agora crie um PDF em português", "pt"),
            ("والآن اختصره بالعربية", "ar"),
        )
        previous = None
        for text, expected in turns:
            decision = engine.decide(text, preferred="auto", previous=previous, fallback="es")
            self.assertEqual(decision.response_language, expected)
            previous = decision.response_language
        self.assertEqual(engine.decide("DNS?", preferred="auto", previous=previous).response_language, "ar")

    def test_explicit_response_language_understands_every_language_name(self) -> None:
        engine = LanguageContextEngine()
        prompts = {
            "es": "Please reply in Spanish", "en": "Responde en inglés",
            "pt": "Reply in Portuguese", "fr": "Reply in French", "de": "Reply in German",
            "it": "Reply in Italian", "zh": "Responde en chino", "ja": "Responde en japonés",
            "ko": "Responde en coreano", "ru": "Responde en ruso", "ar": "Responde en árabe",
            "hi": "Reply in Hindi",
        }
        for locale, prompt in prompts.items():
            with self.subTest(locale=locale):
                self.assertEqual(engine.explicit_request(prompt), locale)

    def test_deterministic_messages_never_fall_back_to_another_language(self) -> None:
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                values = {
                    core_message("status", locale), identity_message(locale),
                    product_help_message(locale, "overview"),
                    product_help_message(locale, "voice"), response_directive(locale),
                }
                self.assertEqual(len(values), 5)
                self.assertTrue(all(value.strip() for value in values))

    def test_system_status_fast_path_is_available_in_all_locales(self) -> None:
        router = ModelRouter()
        for locale, probe in {
            "es": "estado del sistema", "en": "system status", "pt": "estado do sistema",
            "fr": "état du système", "de": "Systemstatus", "it": "stato del sistema",
            "zh": "系统状态", "ja": "システム状態", "ko": "시스템 상태",
            "ru": "состояние системы", "ar": "حالة النظام", "hi": "सिस्टम की स्थिति",
        }.items():
            with self.subTest(locale=locale):
                self.assertEqual(router.route(probe).decision, RouteDecision.TOOL)

    def test_ui_voice_and_ghost_catalogs_match_reference_keys(self) -> None:
        root = UI_ROOT / "locales"
        for prefix in ("", "voice-", "ghost-"):
            reference = json.loads((root / f"{prefix}es.json").read_text(encoding="utf-8"))
            for locale in SUPPORTED_LOCALES:
                with self.subTest(prefix=prefix or "ui", locale=locale):
                    target = json.loads((root / f"{prefix}{locale}.json").read_text(encoding="utf-8"))
                    self.assertEqual(set(target), set(reference))
                    self.assertTrue(all(str(value).strip() for value in target.values()))

    def test_arabic_is_the_only_rtl_locale(self) -> None:
        self.assertEqual(locale_direction("ar"), "rtl")
        self.assertTrue(all(locale_direction(code) == "ltr" for code in SUPPORTED_LOCALES if code != "ar"))
        self.assertEqual(LOCALE_SPECS["ar"].native_name, "العربية")

    def test_rtl_and_cjk_ui_have_script_aware_layout_rules(self) -> None:
        css = (UI_ROOT / "polish.css").read_text(encoding="utf-8")
        for selector in ('html[dir="rtl"] .sidebar', 'html[lang="zh"] body', 'html[lang="ja"] body', 'html[lang="ko"] body', 'html[lang="hi"] body'):
            self.assertIn(selector, css)

    def test_document_profile_uses_script_fonts_and_real_word_rtl(self) -> None:
        self.assertEqual(DocumentStyleProfile.for_locale("zh").font_family, "Microsoft YaHei")
        self.assertEqual(DocumentStyleProfile.for_locale("hi").font_family, "Nirmala UI")
        arabic = DocumentStyleProfile.for_locale("ar")
        self.assertEqual(arabic.direction, "rtl")
        from docx import Document
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "arabic.docx"
            document = Document(); arabic.apply_docx(document); document.add_paragraph("اختبار عربي"); document.save(output)
            with zipfile.ZipFile(output) as archive:
                styles = archive.read("word/styles.xml").decode("utf-8")
        self.assertIn("w:bidi", styles)
        self.assertIn("w:cs=\"Segoe UI\"", styles)

    def test_natural_language_actions_cover_all_twelve_languages(self) -> None:
        repair = NaturalLanguageRepair()
        commands = {
            "es": "por favor crea un archivo PDF", "en": "please create a PDF file", "pt": "por favor crie um arquivo PDF",
            "fr": "s'il vous plaît crée un fichier PDF", "de": "bitte erstelle eine PDF Datei", "it": "per favore crea un file PDF",
            "zh": "创建 PDF", "ja": "PDFを作成", "ko": "PDF를 만들어 주세요",
            "ru": "создай PDF", "ar": "أنشئ PDF", "hi": "PDF बनाओ",
        }
        for locale, command in commands.items():
            with self.subTest(locale=locale):
                interpreted = repair.interpret(command)
                self.assertEqual(interpreted.action, "create")
                self.assertEqual(interpreted.language, locale)

    def test_music_queries_keep_unicode_and_strip_multilingual_play_verbs(self) -> None:
        commands = {
            "pt": ("reproduza Julieta de Latin Mafia", "Julieta"),
            "fr": ("joue Julieta de Latin Mafia", "Julieta"),
            "de": ("spiele Julieta von Latin Mafia", "Julieta"),
            "zh": ("播放夜曲", "夜曲"), "ja": ("再生 夜に駆ける", "夜に駆ける"),
            "ko": ("재생 밤편지", "밤편지"), "ru": ("включи Звезда", "Звезда"),
            "ar": ("شغل تملي معاك", "تملي معاك"), "hi": ("बजाओ तुम ही हो", "तुम ही हो"),
        }
        for locale, (command, expected) in commands.items():
            with self.subTest(locale=locale):
                query = MediaSearchQuery.parse(command)
                self.assertEqual(query.title, expected)
                self.assertTrue(normalize_media(query.title))

    def test_quality_gate_reports_missing_voice_models_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "vosk-model-small-es-0.42").mkdir()
            report = MultilingualQualityGate(UI_ROOT / "locales", model_dir).evaluate(tts_locales=("es",))
        rows = {item["locale"]: item for item in report["locales"]}
        self.assertEqual(rows["es"]["stt"], "PACKAGED_TESTED")
        self.assertEqual(rows["pt"]["stt"], "MODEL_NOT_INSTALLED")
        self.assertEqual(rows["pt"]["tts"], "NOT_RUNTIME_VERIFIED")
        self.assertEqual(report["summary"]["user_verified"], 0)


if __name__ == "__main__":
    unittest.main()
