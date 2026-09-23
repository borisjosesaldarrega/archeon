from __future__ import annotations

import unittest

from archeon.media.matcher import MediaSearchQuery, is_unknown_artist, normalize, rank_candidates
from archeon.media.providers import MediaSearchResult


def track(identifier: str, title: str, artist: str = "Latin Mafia", **metadata: object) -> MediaSearchResult:
    return MediaSearchResult(
        id=identifier, provider=str(metadata.pop("provider", "audius")),
        title=title, artist=artist, **metadata,
    )


class MediaMatcherTests(unittest.TestCase):
    def test_artist_dash_title_uses_common_music_order(self) -> None:
        query = MediaSearchQuery.parse("reproduce Joji - Glimpse of Us")
        self.assertEqual(query.artist, "Joji")
        self.assertEqual(query.title, "Glimpse of Us")
        self.assertEqual(query.provider_query, "Glimpse of Us Joji")

    def test_provider_placeholder_artist_can_use_explicit_user_artist(self) -> None:
        self.assertTrue(is_unknown_artist("Anonimo"))
        self.assertTrue(is_unknown_artist("Unknown Artist"))
        self.assertFalse(is_unknown_artist("Duki"))

    def test_exact_original_beats_remix(self) -> None:
        query = MediaSearchQuery.parse("reproduce Julieta de Latin Mafia")
        ranked = rank_candidates(query, [
            track("remix", "Julieta (SAU Remix)", "SAU", popularity=2_000_000),
            track("original", "Julieta", is_verified_artist=True, popularity=10_000),
        ])
        self.assertEqual(ranked[0].candidate.id, "original")
        self.assertFalse(ranked[0].is_alternative)

    def test_requested_remix_beats_original(self) -> None:
        query = MediaSearchQuery.parse("pon el remix de Julieta de Latin Mafia")
        ranked = rank_candidates(query, [
            track("original", "Julieta", is_verified_artist=True),
            track("remix", "Julieta Remix"),
        ])
        self.assertEqual(query.requested_version, "remix")
        self.assertEqual((query.title, query.artist), ("Julieta", "Latin Mafia"))
        self.assertEqual(ranked[0].candidate.id, "remix")

    def test_requested_live_version_beats_studio_version(self) -> None:
        query = MediaSearchQuery.parse("reproduce la versión en vivo de Brillas de León Larregui")
        ranked = rank_candidates(query, [
            track("studio", "Brillas", "León Larregui"),
            track("live", "Brillas (En Vivo)", "León Larregui"),
        ])
        self.assertEqual(query.requested_version, "live")
        self.assertEqual((query.title, query.artist), ("Brillas", "León Larregui"))
        self.assertEqual(ranked[0].candidate.id, "live")

    def test_title_only_does_not_invent_an_artist(self) -> None:
        query = MediaSearchQuery.parse("toca Eres")
        self.assertEqual(query.title, "Eres")
        self.assertEqual(query.artist, "")

    def test_any_version_explicitly_allows_alternatives(self) -> None:
        query = MediaSearchQuery.parse("reproduce cualquier versión de Julieta de Latin Mafia")
        self.assertTrue(query.allow_alternatives)
        self.assertEqual(query.requested_version, "original")
        self.assertEqual(query.title, "Julieta")
        self.assertEqual(query.artist, "Latin Mafia")

    def test_normalization_handles_accents_punctuation_and_feat(self) -> None:
        self.assertEqual(normalize("  CANCIÓN — feat. Álvaro! "), "cancion alvaro")

    def test_original_first_gate_beats_popular_edit_and_remix(self) -> None:
        query = MediaSearchQuery.parse("reproduce Se Fue La Luz de Latin Mafia")
        ranked = rank_candidates(query, [
            track("edit", "LATIN MAFIA - Se Fue La Luz (JSSE Edit)", "JSSE", popularity=9_000_000),
            track("remix", "Se Fue La Luz - Nightcore Remix", "Fan Upload", popularity=20_000_000),
            track("original", "Se Fue La Luz", "Latin Mafia", is_verified_artist=True, popularity=1_000),
        ])
        self.assertEqual(ranked[0].candidate.id, "original")
        self.assertGreater(ranked[0].total, ranked[1].total)

    def test_limon_y_sal_normalizes_accents_without_losing_identity(self) -> None:
        query = MediaSearchQuery.parse("reproduce limon y sal de julieta venegas")
        ranked = rank_candidates(query, [
            track("original", "Limón y Sal", "Julieta Venegas", is_verified_artist=True),
            track("karaoke", "Limon y Sal Karaoke", "Karaoke Hits", popularity=2_000_000),
        ])
        self.assertEqual((normalize(query.title), normalize(query.artist)), ("limon y sal", "julieta venegas"))
        self.assertEqual(ranked[0].candidate.id, "original")


if __name__ == "__main__":
    unittest.main()
