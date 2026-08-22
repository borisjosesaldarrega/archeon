import unittest

from archeon.ui.ghost_native import radial_action_ids


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
