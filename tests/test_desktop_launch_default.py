from __future__ import annotations

import unittest

from archeon.__main__ import build_parser


class DesktopLaunchDefaultTests(unittest.TestCase):
    def test_normal_launch_does_not_select_browser_or_headless_mode(self) -> None:
        arguments = build_parser().parse_args([])
        self.assertFalse(arguments.browser)
        self.assertFalse(arguments.headless)


if __name__ == "__main__":
    unittest.main()
