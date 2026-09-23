from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.agent import CapabilityRouter
from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault
from archeon.media import MediaState
from archeon.understanding import CommandConfidence, NaturalLanguageRepair, NegationScopeResolver


class IntentGuardUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.negation = NegationScopeResolver()

    def test_human_situation_is_not_an_artifact_creation_command(self) -> None:
        interpreted = NaturalLanguageRepair().interpret(
            "Tengo una entrevista de trabajo y el horario choca con mis estudios; dime qué hago."
        )
        self.assertEqual(interpreted.action, "respond")

    def test_negated_delete_is_not_destructive(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("No borrar ese archivo", known_files=("uno.txt",))
        self.assertEqual(interpreted.action, "respond")
        self.assertFalse(interpreted.clarification_required)

    def test_indirect_negated_delete_is_not_destructive(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("No quiero borrar ese archivo", known_files=("uno.txt",))
        self.assertEqual(interpreted.action, "respond")
        self.assertFalse(interpreted.clarification_required)

    def test_explicit_ambiguous_delete_still_requires_clarification(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("Borra ese archivo")
        self.assertEqual(interpreted.action, "delete")
        self.assertTrue(interpreted.clarification_required)

    def test_negated_pc_control_is_not_control_request(self) -> None:
        route = CapabilityRouter().route("No usa mi PC; solo dime los pasos")
        self.assertFalse(route.control_requested)

    def test_text_correction_is_not_desktop_control(self) -> None:
        route = CapabilityRouter().route("Corrige la ortografía de esta frase")
        self.assertFalse(route.control_requested)

    def test_currently_is_not_a_current_information_capability(self) -> None:
        route = CapabilityRouter().route("Actualmente estudio por las noches")
        self.assertNotIn("search", [item.value for item in route.capabilities])

    def test_negated_conversion_is_not_an_artifact_action(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("No conviertas el informe en PDF")
        self.assertEqual(interpreted.action, "respond")

    def test_indirect_negated_create_is_not_an_artifact_action(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("No quiero crear un documento; solo dame ideas")
        self.assertEqual(interpreted.action, "respond")

    def test_late_delete_correction_wins(self) -> None:
        interpreted = NaturalLanguageRepair().interpret(
            "Borra el archivo... espera, no lo borres", known_files=("uno.txt",),
        )
        self.assertEqual(interpreted.action, "respond")

    def test_direct_delete_remains_an_action(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("Borra uno.txt", known_files=("uno.txt",))
        self.assertEqual(interpreted.action, "delete")

    def test_direct_conversion_remains_an_action(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("Convierte este Word a PDF")
        self.assertEqual(interpreted.action, "convert")

    def test_pdf_narrative_is_not_creation(self) -> None:
        interpreted = NaturalLanguageRepair().interpret("El profesor pidió un PDF para mañana")
        self.assertEqual(interpreted.action, "respond")

    def test_late_launch_cancellation_is_negated(self) -> None:
        resolution = self.negation.resolve(
            "abre steam... no, mejor no", r"\b(?:abre|abras)\b", context_present=True,
        )
        self.assertEqual(resolution.confidence, CommandConfidence.NEGATED)
        self.assertFalse(resolution.action_allowed)

    def test_late_media_cancellation_is_negated(self) -> None:
        resolution = self.negation.resolve(
            "pausa la música... no, déjala sonando", r"\bpausa\b", context_present=True,
        )
        self.assertEqual(resolution.confidence, CommandConfidence.NEGATED)
        self.assertTrue(resolution.self_corrected)


class FalsePositiveApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data = Path(self.temp.name)
        self.application = ArcheonApplication(
            data_dir=data, port=0,
            auth_provider=DevelopmentAuthProvider(data / "auth.json"),
            auth_vault=MemorySessionVault(),
        )
        self.application.start()

    def tearDown(self) -> None:
        self.application.stop()
        self.temp.cleanup()

    def test_full_job_advice_fixture_never_routes_to_media(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.stop_playback
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command(
                "dame un consejo me ayudaron en darme una palanca para conseguir una entrevista de trabajo "
                "pero en esa entrevista me dijeron el horario y esos horarios no cuadran para mí porque "
                "tendría que dejar de estudiar y la persona que me palanqueó me presiona para que acepte"
            )
        finally:
            self.application.media.stop_playback = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])

    def test_continue_your_studies_does_not_resume_music(self) -> None:
        self.application.media._playback_state = MediaState.PAUSED
        calls: list[str] = []
        original = self.application.media.resume
        try:
            self.application.media.resume = lambda: calls.append("resume") or {"state": "playing"}
            response = self.application.handle_command("Continúa con tus estudios y busca otro empleo.")
        finally:
            self.application.media.resume = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])

    def test_quoted_media_control_word_does_not_control_playback(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.stop_playback
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command(
                "La canción dice detén el miedo, pero quiero entender el significado de esa frase."
            )
        finally:
            self.application.media.stop_playback = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])

    def test_put_me_an_example_does_not_search_music(self) -> None:
        calls: list[str] = []
        original = self.application.handle_action
        try:
            def action(name: str, payload=None):
                if name == "media.search": calls.append(name)
                return original(name, payload)
            self.application.handle_action = action
            response = self.application.handle_command("Ponme un ejemplo de recursión en Python.")
        finally:
            self.application.handle_action = original
        self.assertNotEqual(response.get("data", {}).get("route"), "media_matcher")
        self.assertEqual(calls, [])

    def test_currently_studying_does_not_trigger_news_search(self) -> None:
        calls: list[str] = []
        original = self.application.search.search
        try:
            self.application.search.search = lambda *_args, **_kwargs: calls.append("search") or []
            response = self.application.handle_command("Actualmente estudio por las noches y quiero organizarme mejor.")
        finally:
            self.application.search.search = original
        self.assertNotEqual(response.get("data", {}).get("route"), "live_search")
        self.assertEqual(calls, [])

    def test_negated_news_search_does_not_use_live_search(self) -> None:
        calls: list[str] = []
        original = self.application.search.search
        try:
            self.application.search.search = lambda *_args, **_kwargs: calls.append("search") or []
            response = self.application.handle_command("No busques noticias actuales; ayúdame a ordenar esta idea.")
        finally:
            self.application.search.search = original
        self.assertNotEqual(response.get("data", {}).get("route"), "live_search")
        self.assertEqual(calls, [])

    def test_selected_document_does_not_capture_person_reference(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "document.pdf"
        self.application._task_context.selected_file = str(fixture.resolve())
        response = self.application.handle_command("Esa persona me está presionando; ¿qué debería responderle?")
        self.assertNotIn(response.get("data", {}).get("route"), {"document_agent", "document_grounded_task"})

    def test_document_narrative_is_not_mistaken_for_a_read_command(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "document.pdf"
        self.application._task_context.selected_file = str(fixture.resolve())
        response = self.application.handle_command("El archivo dice mucho sobre quien lo escribió.")
        self.assertNotIn(response.get("data", {}).get("route"), {"document_agent", "document_grounded_task"})

    def test_negated_document_read_is_not_executed(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "document.pdf"
        self.application._task_context.selected_file = str(fixture.resolve())
        response = self.application.handle_command("No leas el PDF; solo quiero hablar del tema.")
        self.assertNotIn(response.get("data", {}).get("route"), {"document_agent", "document_grounded_task"})

    def test_negated_screen_observation_is_not_executed(self) -> None:
        response = self.application.handle_command("No mires mi pantalla; explícame cómo proteger mi privacidad.")
        self.assertNotEqual(response.get("data", {}).get("route"), "desktop_agent")

    def test_pdf_topic_is_not_mistaken_for_artifact_followup(self) -> None:
        self.application._last_document_output = {
            "title": "Informe", "content": "Contenido", "source": "memory",
        }
        self.assertIsNone(
            self.application._handle_artifact_followup("Ahora hablemos sobre PDF", "ahora hablemos sobre pdf")
        )

    def test_general_change_question_is_not_archeon_product_help(self) -> None:
        response = self.application.handle_command("¿Cómo cambiar de trabajo sin dejar mis estudios?")
        self.assertNotEqual(response.get("data", {}).get("route"), "product_help")

    def test_explicit_archeon_change_question_still_uses_product_help(self) -> None:
        response = self.application.handle_command("¿Cómo cambio el tema de Archeon?")
        self.assertEqual(response.get("data", {}).get("route"), "product_help")

    def test_explicit_song_and_short_resume_remain_supported(self) -> None:
        self.application.media._playback_state = MediaState.PAUSED
        calls: list[str] = []
        original = self.application.media.resume
        try:
            self.application.media.resume = lambda: calls.append("resume") or {"state": "playing"}
            response = self.application.handle_command("reanuda")
        finally:
            self.application.media.resume = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertEqual(response.get("data", {}).get("action"), "media.resume")
        self.assertEqual(calls, ["resume"])

    def test_direct_stop_music_remains_supported(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.stop_playback
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command("para la música")
        finally:
            self.application.media.stop_playback = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertEqual(response.get("data", {}).get("action"), "media.stop")
        self.assertEqual(calls, ["stop"])

    def test_contextual_pause_pronoun_remains_supported(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.pause
        try:
            self.application.media.pause = lambda: calls.append("pause") or {"state": "paused"}
            response = self.application.handle_command("pausa eso")
        finally:
            self.application.media.pause = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertEqual(response.get("data", {}).get("action"), "media.pause")
        self.assertEqual(calls, ["pause"])

    def test_negated_stop_music_does_not_stop(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.stop_playback
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command("no no pares la música")
        finally:
            self.application.media.stop_playback = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])

    def test_late_pause_correction_keeps_playing(self) -> None:
        self.application.media._playback_state = MediaState.PLAYING
        calls: list[str] = []
        original = self.application.media.pause
        try:
            self.application.media.pause = lambda: calls.append("pause") or {"state": "paused"}
            response = self.application.handle_command("pausa la música... no, déjala sonando")
        finally:
            self.application.media.pause = original
            self.application.media._playback_state = MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
