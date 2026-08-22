"""Very small Tk/Win32 Ghost window that does not start Chromium."""

from __future__ import annotations

from pathlib import Path
from threading import Thread

from archeon.core.config import GhostConfig
from archeon.core.events import EventBus


class NativeGhostHost:
    def __init__(self, events: EventBus, config: GhostConfig) -> None:
        self._events = events
        self._config = config

    def run(self, *, auto_exit_seconds: float | None = None) -> str:
        import tkinter as tk

        root = tk.Tk(className="ARCHEONGhost")
        size = self._config.size
        x = self._config.position_x
        y = self._config.position_y
        if x is None:
            x = root.winfo_screenwidth() - size - 28
        if y is None:
            y = 48
        root.geometry(f"{size}x{size}+{x}+{y}")
        root.overrideredirect(True)
        root.attributes("-topmost", self._config.always_on_top)
        root.attributes("-alpha", self._config.opacity)
        transparent = "#010101"
        root.configure(bg=transparent)
        try:
            root.wm_attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass

        canvas = tk.Canvas(
            root,
            width=size,
            height=size,
            bg=transparent,
            highlightthickness=0,
            cursor="hand2",
        )
        canvas.pack(fill="both", expand=True)
        image = tk.PhotoImage(file=str(Path(__file__).resolve().parent / "logo_asitente.png"))
        reduction = max(1, max(image.width(), image.height()) // max(64, size - 14))
        image = image.subsample(reduction, reduction)
        canvas.create_oval(4, 4, size - 4, size - 4, outline="#08d9ff", width=2)
        canvas.create_image(size // 2, size // 2, image=image)
        canvas.create_text(size - 15, size - 13, text="↗", fill="#08d9ff", font=("Segoe UI", 9))

        outcome = "exit"
        drag = {"x": 0, "y": 0}

        def begin_drag(event) -> None:
            drag["x"], drag["y"] = event.x_root, event.y_root

        def move(event) -> None:
            dx, dy = event.x_root - drag["x"], event.y_root - drag["y"]
            root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")
            drag["x"], drag["y"] = event.x_root, event.y_root

        def expand(*_: object) -> None:
            nonlocal outcome
            outcome = "main"
            root.quit()

        canvas.bind("<ButtonPress-1>", begin_drag)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<Double-Button-1>", expand)
        canvas.bind("<Button-3>", expand)

        subscription = self._events.subscribe("ui.window.*", max_queue=8)

        def bridge() -> None:
            try:
                while True:
                    event = subscription.get()
                    if event.type == "ui.window.main":
                        root.after(0, expand)
                    elif event.type == "ui.window.exit":
                        root.after(0, root.quit)
            except RuntimeError:
                pass

        bridge_thread = Thread(target=bridge, name="archeon-ghost-bridge", daemon=False)
        bridge_thread.start()
        if auto_exit_seconds is not None:
            root.after(max(1, int(auto_exit_seconds * 1000)), root.quit)
        try:
            root.mainloop()
        finally:
            subscription.close()
            bridge_thread.join(timeout=2.0)
            root.destroy()
        return outcome
