import math
import unittest

from archeon.ui.ghost_native import radial_action_ids, radial_layout


class GhostNativeTests(unittest.TestCase):
    def test_radial_actions_are_contextual_and_complete(self) -> None:
        self.assertEqual(
            radial_action_ids("idle"),
            ("open", "listen", "apps", "games", "favorites", "settings"),
        )
        self.assertEqual(
            radial_action_ids("playing"),
            ("previous", "play_pause", "next", "volume_down", "volume_up", "choose_music", "open"),
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
