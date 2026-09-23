"""Real M4 mouse/cursor test over a controlled red target."""

from __future__ import annotations

import ctypes
import json
import threading
import time
import tkinter as tk
from pathlib import Path

from archeon.desktop.mouse import WindowsMouseFallback
from archeon.desktop.windows import WindowsDesktopController, WindowsDesktopObserver


def main() -> int:
    ready = threading.Event()
    changed = threading.Event()
    shared: dict[str, object] = {}

    def ui() -> None:
        window = tk.Tk()
        window.title("ARCHEON M4 Mouse Cursor")
        window.geometry("760x480+160+120")
        canvas = tk.Canvas(window, bg="#081116", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            380, 95, text="ARCHI CONTROL TEST", fill="#00e5ff", font=("Segoe UI", 22, "bold"),
        )
        target = canvas.create_rectangle(285, 190, 475, 300, fill="#d92d20", outline="#ff7a70", width=4)
        label = canvas.create_text(380, 245, text="RED TARGET", fill="white", font=("Segoe UI", 18, "bold"))

        def click(event: tk.Event) -> None:
            if 285 <= event.x <= 475 and 190 <= event.y <= 300:
                canvas.itemconfigure(target, fill="#039855", outline="#6ce9a6")
                canvas.itemconfigure(label, text="VERIFIED")
                changed.set()

        canvas.bind("<Button-1>", click)
        window.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shared["handle"] = int(user32.GetAncestor(int(window.winfo_id()), 2) or window.winfo_id())
        shared["target"] = (
            window.winfo_rootx() + 285, window.winfo_rooty() + 190,
            window.winfo_rootx() + 475, window.winfo_rooty() + 300,
        )
        ready.set()
        window.mainloop()

    thread = threading.Thread(target=ui, name="m4-mouse-cursor-fixture")
    thread.start()
    if not ready.wait(5):
        raise TimeoutError("controlled_window_start_timeout")
    handle = int(shared["handle"])
    target = tuple(int(value) for value in shared["target"])
    observer = WindowsDesktopObserver()
    WindowsDesktopController._focus_window(handle)
    time.sleep(0.3)
    active = observer.active_window()
    mouse = WindowsMouseFallback(observer=observer)
    started = time.perf_counter()
    try:
        result = mouse.perform(
            "left_click", window_handle=handle, observed_window_bounds=active.bounds,
            target_bounds=target, show_cursor=True,
        )
        changed_ok = changed.wait(1.0)
        screenshot = ""
        try:
            from PIL import ImageGrab

            screenshot_path = Path("benchmarks/desktop-agent-m4-mouse-cursor.png")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=active.bounds, all_screens=True).save(screenshot_path)
            screenshot = str(screenshot_path.resolve())
        except Exception:
            screenshot = "capture_unavailable"
        report = {
            "ok": bool(changed_ok and result["cursor_position_verified"]),
            "action": result["action"],
            "visual_state_changed": changed_ok,
            "cursor_overlay": result["cursor_overlay"],
            "cursor_position_verified": result["cursor_position_verified"],
            "target_revalidated": result["target_revalidated"],
            "held_buttons": result["held_buttons"],
            "screenshot": screenshot,
            "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        mouse.release_all()
        ctypes.WinDLL("user32", use_last_error=True).PostMessageW(handle, 0x0010, 0, 0)
        thread.join(timeout=5)
    output = Path("benchmarks/desktop-agent-m4-mouse-cursor.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] and not report["held_buttons"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
