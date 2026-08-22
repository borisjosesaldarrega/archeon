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


def choose_visual_file(kind: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    choices = {
        "image": (("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"),),
        "video": (("Videos", "*.mp4 *.webm *.m4v"),),
        "logo": (("Logos", "*.png *.jpg *.jpeg *.webp"),),
    }
    if kind not in choices:
        raise ValueError("invalid_visual_kind")
    root = tk.Tk(className="ARCHEONVisualPicker")
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        value = filedialog.askopenfilename(parent=root, title="Personalizar ARCHEON", filetypes=choices[kind] + (("Todos", "*.*"),))
        return str(value) if value else None
    finally:
        root.destroy()
