from __future__ import annotations

import unittest
from dataclasses import dataclass

from archeon.desktop.cursor import ArchiCursorOverlay
from archeon.desktop.mouse import WindowsMouseFallback


@dataclass
class FakeWindow:
    handle: int = 42
    bounds: tuple[int, int, int, int] = (0, 0, 1000, 800)

    def public(self) -> dict[str, object]:
        return {"handle": self.handle, "bounds": self.bounds, "title": "Fixture"}


class FakeObserver:
    def active_window(self) -> FakeWindow:
        return FakeWindow()


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, int], str]] = []

    def show(self, point: tuple[int, int], **options: object) -> dict[str, object]:
        self.calls.append((point, str(options["state"])))
        return {"shown": True, "click_through": True, "resident": False}


class RecordingMouse(WindowsMouseFallback):
    def __init__(self) -> None:
        self.fake_cursor = FakeCursor()
        super().__init__(observer=FakeObserver(), cursor=self.fake_cursor)
        self.events: list[tuple[int, int, int, int]] = []
        self.position = (0, 0)

    def _move(self, x: int, y: int) -> None:
        self.position = (x, y)

    def _send(self, dx: int, dy: int, data: int, flags: int) -> None:
        self.events.append((dx, dy, data, flags))

    def _cursor_position(self) -> tuple[int, int]:
        return self.position

    def perform_action(self, action: str, **options: object) -> dict[str, object]:
        return self.perform(
            action,
            window_handle=42,
            observed_window_bounds=(0, 0, 1000, 800),
            target_bounds=(100, 100, 200, 200),
            **options,
        )


class DesktopMouseTests(unittest.TestCase):
    def test_click_variants_emit_expected_native_flags_and_cursor_states(self) -> None:
        mouse = RecordingMouse()
        expected = {
            "left_click": ([0x0002, 0x0004], "click"),
            "double_click": ([0x0002, 0x0004, 0x0002, 0x0004], "double_click"),
            "right_click": ([0x0008, 0x0010], "click"),
            "middle_click": ([0x0020, 0x0040], "click"),
        }
        for action, (flags, cursor_state) in expected.items():
            mouse.events.clear()
            result = mouse.perform_action(action)
            self.assertEqual([event[3] for event in mouse.events], flags)
            self.assertEqual(result["cursor_overlay"]["resident"], False)
            self.assertEqual(mouse.fake_cursor.calls[-1][1], cursor_state)
            self.assertTrue(result["cursor_position_verified"])

    def test_vertical_and_horizontal_scroll_remain_separate(self) -> None:
        mouse = RecordingMouse()
        mouse.perform_action("scroll_vertical", scroll_delta=-240)
        mouse.perform_action("scroll_horizontal", scroll_delta=120)
        self.assertEqual(mouse.events[-2][2:], (-240, 0x0800))
        self.assertEqual(mouse.events[-1][2:], (120, 0x1000))

    def test_press_release_drag_drop_and_close_never_leave_button_held(self) -> None:
        mouse = RecordingMouse()
        pressed = mouse.perform_action("press", button="middle")
        self.assertEqual(pressed["held_buttons"], ["middle"])
        mouse.release_all()
        self.assertEqual(mouse._held_buttons, set())
        dragged = mouse.perform_action("drag", destination=(400, 350), button="left")
        self.assertEqual(dragged["cursor_position"], [400, 350])
        self.assertTrue(dragged["cursor_position_verified"])
        dropped = mouse.perform_action("drop", destination=(500, 450), button="right")
        self.assertEqual(dropped["held_buttons"], [])

    def test_window_and_target_are_revalidated_before_input(self) -> None:
        mouse = RecordingMouse()
        with self.assertRaisesRegex(RuntimeError, "target_window_changed"):
            mouse.perform(
                "move", window_handle=99, observed_window_bounds=(0, 0, 1000, 800),
                target_bounds=(100, 100, 200, 200),
            )
        with self.assertRaisesRegex(ValueError, "invalid_target_rectangle"):
            mouse.perform(
                "move", window_handle=42, observed_window_bounds=(0, 0, 1000, 800),
                target_bounds=(100, 100, 100, 200),
            )

    def test_cursor_rejects_unknown_state_before_creating_native_resources(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_cursor_state"):
            ArchiCursorOverlay().show((10, 10), state="unknown")


if __name__ == "__main__":
    unittest.main()
