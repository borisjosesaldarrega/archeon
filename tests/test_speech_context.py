import unittest

from archeon.voice.context import SpeechContextResolver, SpeechTarget, normalize_speech


class SpeechContextResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = (
            SpeechTarget("spotify", "Spotify", ("spoty", "mi musica"), "app"),
            SpeechTarget("valorant", "VALORANT", ("valor ant",), "game"),
            SpeechTarget("vscode", "Visual Studio Code", ("visual code", "codigo"), "app"),
        )
        self.resolver = SpeechContextResolver(self.targets)

    def test_normalization_preserves_only_semantic_comparison_text(self) -> None:
        self.assertEqual(normalize_speech("  ¡Ábrelo, por favor!  "), "abrelo por favor")

    def test_separates_wake_name_variants_from_multilingual_command(self) -> None:
        for phrase in ("Archeón, abre Spotify", "Arqueón abre Spotify", "Archi on abre Spotify"):
            with self.subTest(phrase=phrase):
                result = self.resolver.resolve(phrase, require_wake=True)
                self.assertTrue(result.wake_detected)
                self.assertTrue(result.matched)
                self.assertEqual(result.target_id, "spotify")
        english = self.resolver.resolve("Nova open Visual Code", wake_name="Nova", require_wake=True)
        self.assertEqual(english.target_id, "vscode")

    def test_does_not_accept_wake_name_inside_an_unrelated_word(self) -> None:
        result = self.resolver.resolve("archivo abre Spotify", require_wake=True)
        self.assertFalse(result.wake_detected)
        self.assertEqual(result.reason, "wake_not_detected")

    def test_resolves_orthographic_and_simple_phonetic_stt_errors(self) -> None:
        self.assertEqual(self.resolver.resolve("abre spotifai").target_id, "spotify")
        valorant = self.resolver.resolve("inicia balor ant")
        self.assertEqual(valorant.target_id, "valorant")
        self.assertGreaterEqual(valorant.confidence, 0.78)

    def test_resolves_the_product_milestone_stain_to_installed_steam(self) -> None:
        resolver = SpeechContextResolver((SpeechTarget("steam", "Steam"),))
        result = resolver.resolve("abre stain")
        self.assertEqual(result.target_id, "steam")
        self.assertGreaterEqual(result.confidence, 0.78)

    def test_prefers_explicit_alias_and_returns_canonical_display_name(self) -> None:
        result = self.resolver.resolve("ejecuta visual code")
        self.assertEqual(result.target_id, "vscode")
        self.assertEqual(result.target_name, "Visual Studio Code")
        self.assertEqual(result.corrected_text, "open Visual Studio Code")

    def test_never_contextually_corrects_arbitrary_conversation(self) -> None:
        result = self.resolver.resolve("Spotify tiene música interesante")
        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "missing_launch_intent")
        self.assertIsNone(result.corrected_text)

    def test_unknown_launch_target_is_not_invented(self) -> None:
        result = self.resolver.resolve("abre una aplicación desconocida")
        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "no_grounded_match")

    def test_close_catalog_matches_are_reported_as_ambiguous(self) -> None:
        resolver = SpeechContextResolver((
            SpeechTarget("code-a", "Code Alpha"),
            SpeechTarget("code-b", "Code Alfo"),
        ))
        result = resolver.resolve("abre code alfe")
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "ambiguous_target")
        self.assertEqual(len(result.alternatives), 2)

    def test_callers_can_supply_provider_neutral_mappings_per_request(self) -> None:
        resolver = SpeechContextResolver()
        result = resolver.resolve(
            "launch halo infinit",
            targets=({"id": "halo", "name": "Halo Infinite", "kind": "game", "aliases": []},),
        )
        self.assertEqual(result.target_id, "halo")
        self.assertEqual(result.target_kind, "game")


if __name__ == "__main__":
    unittest.main()
