"""Disposable native full-window probe used only for frontend measurements."""

from __future__ import annotations

import argparse
import tkinter as tk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-exit", type=float, default=8.0)
    args = parser.parse_args()

    root = tk.Tk(className="ARCHEONNativeProbe")
    root.title("ARCHEON — native feasibility probe")
    root.geometry("1100x720")
    root.configure(bg="#050507")

    canvas = tk.Canvas(root, bg="#050507", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(74, 70, text="ARCHEON", fill="#f4f7fa", anchor="w", font=("Segoe UI Light", 32))
    canvas.create_text(76, 105, text="NEURAL INTERFACE SYSTEM", fill="#00e6f0", anchor="w", font=("Consolas", 9))
    for radius, color, width in ((190, "#073940", 1), (132, "#08616b", 1), (76, "#00d8e5", 2)):
        canvas.create_oval(550 - radius, 360 - radius, 550 + radius, 360 + radius, outline=color, width=width)
    canvas.create_text(550, 360, text="A", fill="#00edf5", font=("Segoe UI Light", 54))
    canvas.create_text(550, 585, text="IDLE", fill="#00e6f0", font=("Segoe UI Light", 18))
    canvas.create_text(550, 610, text="Sistema local preparado", fill="#7b8790", font=("Consolas", 9))

    panel = tk.Frame(root, bg="#101014", highlightbackground="#17434a", highlightthickness=1)
    panel.place(relx=0.77, rely=0.5, anchor="center", width=270, height=410)
    tk.Label(panel, text="SISTEMA DE ACCESO", fg="#00e6f0", bg="#101014", font=("Consolas", 8)).pack(pady=(42, 10))
    tk.Label(panel, text="Bienvenido a ARCHEON", fg="#f4f7fa", bg="#101014", font=("Segoe UI Light", 18)).pack(pady=(0, 35))
    for text in ("INICIAR SESIÓN", "REGISTRARSE", "CONTINUAR COMO INVITADO"):
        tk.Button(
            panel, text=text, fg="#00e6f0", bg="#11161a", activebackground="#16262a",
            activeforeground="#ffffff", relief="flat", bd=0, font=("Segoe UI Semibold", 9),
        ).pack(fill="x", padx=28, pady=7, ipady=10)

    root.after(max(1, int(args.auto_exit * 1000)), root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
