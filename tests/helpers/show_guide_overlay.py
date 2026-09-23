"""Manual packaged-test helper for the short-lived native GUIDE overlay."""

from __future__ import annotations

import time
from pathlib import Path

from PIL import ImageGrab

from archeon.desktop.overlay import GuideOverlay
from archeon.desktop.windows import WindowsDesktopController


def main() -> None:
    controller = WindowsDesktopController()
    matches = controller.observer.find_windows(title="notepad.txt")
    if not matches:
        raise RuntimeError("controlled_notepad_fixture_not_open")
    target = matches[0]
    controller.manage_window("focus", handle=target.handle)
    located = controller.locate("Archivo")
    overlay = GuideOverlay()
    result = overlay.show(
        tuple(located["bounds"]), label="ARCHI: Archivo", duration_ms=8_000,
    )
    if not result["shown"] or not result["click_through"]:
        raise RuntimeError("guide_overlay_not_verified")
    time.sleep(0.3)
    left, top, right, bottom = located["bounds"]
    capture = ImageGrab.grab(
        bbox=(left - 25, top - 25, right + 160, bottom + 60), all_screens=True,
    )
    capture.save(Path.home() / "AppData" / "Local" / "Temp" / "archeon-m2-guide-test.png")
    time.sleep(8.5)


if __name__ == "__main__":
    main()
