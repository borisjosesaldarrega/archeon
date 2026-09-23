"""Real active-window UIA -> ARCHI Vision fallback milestone."""

from __future__ import annotations

import ctypes
import json
import time
import tkinter as tk
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.desktop.windows import WindowsDesktopController


def main() -> int:
    window = tk.Tk()
    window.title("ARCHEON M3 Controlled Canvas")
    window.geometry("900x560+120+100")
    canvas = tk.Canvas(window, width=900, height=560, bg="#f5f7fa", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_rectangle(100, 90, 800, 460, fill="white", outline="#344054", width=3)
    canvas.create_text(450, 155, text="ARCHEON - Configuration Error", font=("Segoe UI", 20))
    canvas.create_text(450, 265, text="Wake detector could not start.", fill="#b00020", font=("Segoe UI", 17))
    canvas.create_rectangle(590, 365, 740, 425, fill="#e5e7eb", outline="#344054")
    canvas.create_text(665, 395, text="OK", font=("Segoe UI", 14))
    window.update_idletasks(); window.update()
    handle = int(window.winfo_id())
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle = int(user32.GetAncestor(handle, 2) or handle)  # GA_ROOT
    user32.ShowWindow(handle, 9); WindowsDesktopController._focus_window(handle)
    window.update(); time.sleep(0.2)
    app = ArcheonApplication()
    app.start()
    WindowsDesktopController._focus_window(handle); window.update(); time.sleep(0.2)
    started = time.perf_counter()
    try:
        response = app.handle_command("Archeon, mira esta ventana y dime qué está fallando.")
        evidence = response.get("data", {}).get("evidence", {})
        WindowsDesktopController._focus_window(handle); window.update(); time.sleep(0.2)
        guide = app.handle_command("Archeon, muéstrame dónde darle al botón OK.")
        report = {"ok": bool(response.get("ok") and evidence.get("method") == "archi_vision"),
                      "message": response.get("message"),
                      "route": response.get("data", {}).get("route"), "method": evidence.get("method"),
                      "uia_provider": evidence.get("provider"),
                      "uia_names": [item.get("name") for item in evidence.get("elements", [])[:20]],
                      "summary": evidence.get("window_summary"), "errors": evidence.get("errors", []),
                      "confidence": evidence.get("confidence"), "controls": evidence.get("controls", []),
                      "metrics": evidence.get("metrics", {}),
                      "wall_ms": round((time.perf_counter() - started) * 1000, 3),
                      "screenshot_persisted": evidence.get("metrics", {}).get("screenshot_persisted"),
                  "guide": {"ok": guide.get("ok"), "message": guide.get("message"),
                            "method": guide.get("data", {}).get("method"),
                            "highlight": guide.get("data", {}).get("highlight")},
                  "unload": app.handle_action("vision.unload")}
    finally:
        app.stop()
    window.destroy()
    target = Path("benchmarks/desktop-agent-m3-observe.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] and report["unload"].get("state") == "unloaded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
