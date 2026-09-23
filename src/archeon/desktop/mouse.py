"""DPI-aware mouse input used only after structured interaction fails."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Any

from .cursor import ArchiCursorOverlay
from .windows import WindowsDesktopObserver


BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}


def normalize_virtual_point(x: int, y: int, virtual_bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, width, height = virtual_bounds
    if width <= 1 or height <= 1:
        raise ValueError("invalid_virtual_screen")
    normalized_x = round((x - left) * 65535 / (width - 1))
    normalized_y = round((y - top) * 65535 / (height - 1))
    return max(0, min(65535, normalized_x)), max(0, min(65535, normalized_y))


class WindowsMouseFallback:
    def __init__(self, *, observer: Any | None = None, cursor: Any | None = None) -> None:
        self.observer = observer or WindowsDesktopObserver()
        self.cursor = cursor or ArchiCursorOverlay()
        self._held_buttons: set[str] = set()

    def perform(
        self,
        action: str,
        *,
        window_handle: int,
        observed_window_bounds: tuple[int, int, int, int],
        target_bounds: tuple[int, int, int, int],
        destination: tuple[int, int] | None = None,
        scroll_delta: int = 0,
        button: str = "left",
        show_cursor: bool = True,
        reduce_motion: bool = False,
        accent_bgr: int = 0xFFFF00,
        movement_mode: str = "normal",
    ) -> dict[str, Any]:
        active = self.observer.active_window()
        if active.handle != window_handle:
            raise RuntimeError("target_window_changed")
        if any(abs(a - b) > 1 for a, b in zip(active.bounds, observed_window_bounds)):
            raise RuntimeError("window_bounds_changed")
        left, top, right, bottom = target_bounds
        if right <= left or bottom <= top:
            raise ValueError("invalid_target_rectangle")
        if right < active.bounds[0] or bottom < active.bounds[1] or left > active.bounds[2] or top > active.bounds[3]:
            raise RuntimeError("target_outside_window")
        x, y = (left + right) // 2, (top + bottom) // 2
        action = action.casefold().strip()
        aliases = {"scroll": "scroll_vertical", "click": "left_click", "middle": "middle_click"}
        action = aliases.get(action, action)
        button = button.casefold().strip()
        if button not in BUTTON_FLAGS:
            raise ValueError("unsupported_mouse_button")
        movement_mode = movement_mode.casefold().strip()
        if movement_mode not in {"normal", "visible", "fast"}:
            raise ValueError("invalid_mouse_movement_mode")
        self._move_smooth(x, y, mode=movement_mode, reduce_motion=reduce_motion)
        overlay: dict[str, Any] = {"shown": False, "resident": False}
        cursor_state = {
            "move": "moving", "left_click": "click", "right_click": "click",
            "middle_click": "click", "double_click": "double_click", "drag": "drag",
            "drop": "drag", "scroll_vertical": "scroll", "scroll_horizontal": "scroll",
            "press": "targeting", "release": "targeting",
        }.get(action, "targeting")
        if show_cursor:
            overlay = self.cursor.show(
                (x, y), state=cursor_state, reduce_motion=reduce_motion, accent_bgr=accent_bgr,
            )
        if action == "move":
            pass
        elif action == "left_click":
            self._button(*BUTTON_FLAGS["left"])
        elif action == "double_click":
            self._button(*BUTTON_FLAGS["left"])
            time.sleep(0.08)
            self._button(*BUTTON_FLAGS["left"])
        elif action == "right_click":
            self._button(*BUTTON_FLAGS["right"])
        elif action == "middle_click":
            self._button(*BUTTON_FLAGS["middle"])
        elif action == "scroll_vertical":
            self._send(0, 0, int(scroll_delta or 120), 0x0800)
        elif action == "scroll_horizontal":
            self._send(0, 0, int(scroll_delta or 120), 0x1000)
        elif action == "press":
            self._send(0, 0, 0, BUTTON_FLAGS[button][0])
            self._held_buttons.add(button)
        elif action == "release":
            self._send(0, 0, 0, BUTTON_FLAGS[button][1])
            self._held_buttons.discard(button)
        elif action == "drag":
            if destination is None:
                raise ValueError("drag_destination_required")
            self._send(0, 0, 0, BUTTON_FLAGS[button][0])
            self._held_buttons.add(button)
            time.sleep(0.05)
            self._move_smooth(
                int(destination[0]), int(destination[1]),
                mode=movement_mode, reduce_motion=reduce_motion,
            )
            self._send(0, 0, 0, BUTTON_FLAGS[button][1])
            self._held_buttons.discard(button)
        elif action == "drop":
            if destination is not None:
                self._move_smooth(
                    int(destination[0]), int(destination[1]),
                    mode=movement_mode, reduce_motion=reduce_motion,
                )
            self._send(0, 0, 0, BUTTON_FLAGS[button][1])
            self._held_buttons.discard(button)
        else:
            raise ValueError("unsupported_mouse_action")
        cursor_position = self._cursor_position()
        expected_position = (
            tuple(map(int, destination)) if action in {"drag", "drop"} and destination else (x, y)
        )
        return {
            "action": action, "point": [x, y], "target_bounds": list(target_bounds),
            "window": active.public(), "target_revalidated": True,
            "coordinate_space": "physical_virtual_screen", "changed_state": action != "move",
            "button": button, "cursor_overlay": overlay,
            "held_buttons": sorted(self._held_buttons),
            "cursor_position": list(cursor_position),
            "cursor_position_verified": all(
                abs(actual - expected) <= 2
                for actual, expected in zip(cursor_position, expected_position)
            ),
            "input_dispatched": True,
            "movement_mode": movement_mode,
        }

    def release_all(self) -> None:
        for button in tuple(self._held_buttons):
            self._send(0, 0, 0, BUTTON_FLAGS[button][1])
            self._held_buttons.discard(button)

    @staticmethod
    def _cursor_position() -> tuple[int, int]:
        point = wintypes.POINT()
        if not ctypes.WinDLL("user32", use_last_error=True).GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(point.x), int(point.y)

    def _move(self, x: int, y: int) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        virtual = (
            user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78), user32.GetSystemMetrics(79),
        )
        normalized_x, normalized_y = normalize_virtual_point(x, y, virtual)
        self._send(normalized_x, normalized_y, 0, 0x0001 | 0x8000 | 0x4000)

    def _move_smooth(self, x: int, y: int, *, mode: str, reduce_motion: bool) -> None:
        if mode == "fast" or reduce_motion:
            self._move(x, y)
            return
        start_x, start_y = self._cursor_position()
        distance = max(abs(x - start_x), abs(y - start_y))
        duration = 0.42 if mode == "visible" else 0.18
        steps = max(4, min(36, int(distance / 35) + 4))
        delay = duration / steps
        for step in range(1, steps + 1):
            # Smoothstep makes the pointer readable without adding a worker.
            progress = step / steps
            eased = progress * progress * (3.0 - 2.0 * progress)
            next_x = round(start_x + (x - start_x) * eased)
            next_y = round(start_y + (y - start_y) * eased)
            self._move(next_x, next_y)
            if step != steps:
                time.sleep(delay)

    def _button(self, down: int, up: int) -> None:
        self._send(0, 0, 0, down)
        time.sleep(0.04)
        self._send(0, 0, 0, up)

    @staticmethod
    def _send(dx: int, dy: int, data: int, flags: int) -> None:
        ULONG_PTR = wintypes.WPARAM

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = (
                ("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
            )

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))

        class INPUT_UNION(ctypes.Union):
            _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))

        class INPUT(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = (("type", wintypes.DWORD), ("value", INPUT_UNION))

        value = INPUT(0, INPUT_UNION(mi=MOUSEINPUT(dx, dy, data, flags, 0, 0)))
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(value), ctypes.sizeof(INPUT))
        if sent != 1:
            raise ctypes.WinError(ctypes.get_last_error())
