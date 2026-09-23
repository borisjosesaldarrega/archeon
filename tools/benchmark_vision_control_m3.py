"""Real custom-canvas visual CONTROL with post-action verification."""

from __future__ import annotations

import ctypes
import json
import threading
import time
import tkinter as tk
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.core.tools import ToolContext
from archeon.desktop.windows import WindowsDesktopController


def main() -> int:
    ready = threading.Event()
    changed = threading.Event()
    shared: dict[str, int] = {}

    def ui() -> None:
        window = tk.Tk(); window.title("ARCHEON M3 Visual Control")
        window.geometry("900x560+120+100")
        canvas = tk.Canvas(window, width=900, height=560, bg="#f5f7fa", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def paint_error() -> None:
            canvas.delete("all")
            canvas.create_rectangle(100, 90, 800, 460, fill="white", outline="#344054", width=3)
            canvas.create_text(450, 155, text="ARCHEON - Configuration Error", font=("Segoe UI", 20))
            canvas.create_text(450, 265, text="Wake detector could not start.", fill="#b00020", font=("Segoe UI", 17))
            canvas.create_rectangle(590, 365, 740, 425, fill="#e5e7eb", outline="#344054")
            canvas.create_text(665, 395, text="OK", font=("Segoe UI", 14))

        def click(event: tk.Event) -> None:
            if 590 <= event.x <= 740 and 365 <= event.y <= 425:
                canvas.delete("all")
                canvas.create_text(450, 250, text="RESOLVED", fill="#087f5b", font=("Segoe UI", 30))
                changed.set()

        paint_error(); canvas.bind("<Button-1>", click)
        window.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shared["handle"] = int(user32.GetAncestor(int(window.winfo_id()), 2) or window.winfo_id())
        ready.set(); window.mainloop()

    thread = threading.Thread(target=ui, name="m3-controlled-canvas")
    thread.start()
    if not ready.wait(5):
        raise TimeoutError("controlled_window_start_timeout")
    handle = shared["handle"]
    app = ArcheonApplication(); app.start()
    WindowsDesktopController._focus_window(handle); time.sleep(0.3)
    started = time.perf_counter()
    try:
        response = app.handle_command("Archeon, pulsa el botón OK.")
        screenshot_path = Path("benchmarks/evidence/computer_use/fallback_final.png")
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot = "capture_unavailable"
        try:
            from PIL import ImageGrab
            window = app.tools.execute(
                "desktop.observe_active", {"visual_fingerprint": False},
                context=ToolContext(
                    "m10-fallback-capture", scope_permissions=frozenset({"desktop.observe"}),
                ),
            ).data.get("window", {})
            bounds = tuple(window.get("bounds", ()))
            if len(bounds) == 4:
                ImageGrab.grab(bbox=bounds, all_screens=True).save(screenshot_path)
                screenshot = str(screenshot_path.resolve())
        except Exception:
            pass
        report = {"ok": bool(response.get("ok") and changed.wait(1)),
                  "message": response.get("message"), "method": response.get("data", {}).get("method"),
                  "confidence": response.get("data", {}).get("confidence"),
                  "visual_state_changed": changed.is_set(), "wall_ms": round((time.perf_counter()-started)*1000, 3),
                  "screenshot": screenshot, "unload": app.handle_action("vision.unload")}
    finally:
        app.stop()
        ctypes.WinDLL("user32", use_last_error=True).PostMessageW(handle, 0x0010, 0, 0)
        thread.join(timeout=5)
    target = Path("benchmarks/desktop-agent-m3-control.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] and report["method"] == "archi_vision" else 1


if __name__ == "__main__":
    raise SystemExit(main())
