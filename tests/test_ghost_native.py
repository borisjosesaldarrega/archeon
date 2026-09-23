import math
import unittest

from archeon.core.config import GhostConfig
from archeon.core.events import EventBus
from archeon.ui.ghost_native import NativeGhostHost, artwork_id_from_url, radial_action_ids, radial_layout


class GhostNativeTests(unittest.TestCase):
    def test_radial_actions_are_contextual_and_complete(self) -> None:
        self.assertEqual(
            radial_action_ids("idle"),
            ("open", "listen", "apps", "games", "favorites", "settings", "add_shortcut"),
        )
        self.assertEqual(
            radial_action_ids("playing"),
            (
                "previous", "play_pause", "next", "stop", "volume_down", "volume_up",
                "music_panel", "settings", "open",
            ),
        )
        self.assertEqual(radial_action_ids("paused"), radial_action_ids("playing"))

    def test_radial_layout_is_even_and_starts_at_twelve_oclock(self) -> None:
        points = radial_layout(6, center=100, radius=60)
        self.assertEqual(len(points), 6)
        self.assertAlmostEqual(points[0][0], 100)
        self.assertAlmostEqual(points[0][1], 40)
        for x, y in points:
            self.assertAlmostEqual(math.hypot(x - 100, y - 100), 60)
        self.assertAlmostEqual(points[0][0] + points[3][0], 200)
        self.assertAlmostEqual(points[0][1] + points[3][1], 200)

    def test_empty_radial_layout_does_not_create_points(self) -> None:
        self.assertEqual(radial_layout(0, center=50, radius=20), ())

    def test_artwork_identifier_ignores_query_token(self) -> None:
        self.assertEqual(
            artwork_id_from_url("http://127.0.0.1:56789/media/art/remote-cover?token=secret"),
            "remote-cover",
        )
        self.assertIsNone(artwork_id_from_url(None))

    def test_custom_orb_color_is_validated_for_ghost_and_radial(self) -> None:
        host = NativeGhostHost(
            EventBus(), GhostConfig(), action_handler=lambda *_: {"ok": True},
            media_status_handler=lambda: {"state": "stopped"}, artwork_handler=lambda _url: None,
            accent_color="#A855F7",
        )
        self.assertEqual(host._accent_color, "#A855F7")
        invalid = NativeGhostHost(
            EventBus(), GhostConfig(), action_handler=lambda *_: {"ok": True},
            media_status_handler=lambda: {"state": "stopped"}, artwork_handler=lambda _url: None,
            accent_color="red<script>",
        )
        self.assertEqual(invalid._accent_color, "#00F3FF")
