"""Native dialogs loaded only for explicit desktop actions."""

from __future__ import annotations


def choose_audio_files() -> list[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk(className="ARCHEONMediaPicker")
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="Elegir música para ARCHEON",
            filetypes=(
                ("Audio compatible", "*.mp3 *.wav *.flac *.ogg"),
                ("Todos los archivos", "*.*"),
            ),
        )
        return [str(path) for path in selected]
    finally:
        root.destroy()
