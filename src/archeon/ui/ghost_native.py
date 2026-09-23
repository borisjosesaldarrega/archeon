"""Native lightweight Ghost orb with real event and media controls."""

from __future__ import annotations

import json
import gc
import math
import urllib.parse
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from queue import Empty
from typing import Any

from archeon.core.config import GhostConfig
from archeon.core.events import Event, EventBus
from archeon.core.paths import AppPaths, ResourceManager


def radial_action_ids(media_state: str) -> tuple[str, ...]:
    """Return the lightweight contextual action set without creating UI state."""
    if media_state in {"playing", "paused"}:
        return (
            "previous", "play_pause", "next", "stop", "volume_down", "volume_up",
            "music_panel", "settings", "open",
        )
    return ("open", "listen", "apps", "games", "favorites", "settings", "add_shortcut")


def radial_layout(count: int, center: float, radius: float) -> tuple[tuple[float, float], ...]:
    """Return evenly distributed native-canvas centers, starting at twelve o'clock."""
    if count < 1:
        return ()
    return tuple(
        (
            center + math.cos(-math.pi / 2 + (2 * math.pi * index / count)) * radius,
            center + math.sin(-math.pi / 2 + (2 * math.pi * index / count)) * radius,
        )
        for index in range(count)
    )


def artwork_id_from_url(value: str | None) -> str | None:
    """Extract an internal artwork identifier without leaking query credentials."""
    if not value:
        return None
    parsed = urllib.parse.urlparse(str(value))
    identifier = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return urllib.parse.unquote(identifier) if identifier else None


class NativeGhostHost:
    def __init__(
        self,
        events: EventBus,
        config: GhostConfig,
        *,
        action_handler: Callable[[str, dict[str, Any]], dict[str, Any]],
        media_status_handler: Callable[[], dict[str, Any]],
        artwork_handler: Callable[[str], tuple[str, bytes] | None],
        locale: str = "es",
        display_name: str = "Archeon",
        logo_path: str | None = None,
        logo_position_x: float = 0.0,
        logo_position_y: float = 0.0,
        logo_zoom: int = 100,
        accent_color: str = "#00F3FF",
        show_album_art: bool = True,
        vinyl_orb: bool = True,
        resources: ResourceManager | None = None,
    ) -> None:
        self._events = events
        self._config = config
        self._action = action_handler
        self._media_status = media_status_handler
        self._artwork = artwork_handler
        self._display_name = display_name.strip()[:24] or "Archeon"
        self._logo_path = Path(logo_path).expanduser() if logo_path else None
        self._logo_position_x = max(-40.0, min(40.0, float(logo_position_x)))
        self._logo_position_y = max(-40.0, min(40.0, float(logo_position_y)))
        self._logo_zoom = max(100, min(250, int(logo_zoom)))
        candidate_color = str(accent_color).upper()
        self._accent_color = candidate_color if (
            len(candidate_color) == 7 and candidate_color.startswith("#")
            and all(character in "0123456789ABCDEF" for character in candidate_color[1:])
        ) else "#00F3FF"
        self._show_album_art = bool(show_album_art)
        self._vinyl_orb = bool(vinyl_orb)
        self._resources = resources or ResourceManager(AppPaths.discover())
        locale_path = self._resources.ui(f"locales/ghost-{locale}.json")
        if not locale_path.is_file():
            locale_path = locale_path.with_name("ghost-es.json")
        self._text = json.loads(locale_path.read_text(encoding="utf-8"))

    def run(self, *, auto_exit_seconds: float | None = None, open_radial: bool = False) -> str:
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

        canvas = tk.Canvas(root, width=size, height=size, bg=transparent, highlightthickness=0, cursor="hand2")
        canvas.pack(fill="both", expand=True)
        ring = canvas.create_oval(8, 8, size - 8, size - 8, outline=self._accent_color, width=2, tags=("orb",))
        default_logo_path = self._resources.ui("logo_asitente.png")
        logo_source = self._logo_path if self._logo_path and self._logo_path.is_file() else default_logo_path
        try:
            from PIL import Image, ImageDraw, ImageOps, ImageTk

            edge = max(48, size - 20)
            logo_frames = []
            logo_delays: list[int] = []
            with Image.open(logo_source) as source_image:
                frame_count = max(1, int(getattr(source_image, "n_frames", 1)))
                step = max(1, (frame_count + 47) // 48)
                for frame_index in range(0, frame_count, step):
                    source_image.seek(frame_index)
                    image = source_image.convert("RGBA")
                    zoom = self._logo_zoom / 100
                    crop_width, crop_height = image.width / zoom, image.height / zoom
                    left = (image.width - crop_width) / 2 - (self._logo_position_x / 100) * image.width
                    top = (image.height - crop_height) / 2 - (self._logo_position_y / 100) * image.height
                    left = max(0.0, min(image.width - crop_width, left))
                    top = max(0.0, min(image.height - crop_height, top))
                    image = image.crop((left, top, left + crop_width, top + crop_height))
                    image = ImageOps.fit(image, (edge, edge), method=Image.Resampling.LANCZOS)
                    mask = Image.new("L", image.size, 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, image.width - 1, image.height - 1), fill=255)
                    image.putalpha(mask)
                    logo_frames.append(ImageTk.PhotoImage(image, master=root))
                    logo_delays.append(max(50, min(500, int(source_image.info.get("duration", 100))) * step))
            logo = logo_frames[0]
        except (OSError, ValueError):
            logo = tk.PhotoImage(file=str(default_logo_path), master=root)
            reduction = max(1, max(logo.width(), logo.height()) // max(64, size - 14))
            logo = logo.subsample(reduction, reduction)
            logo_frames, logo_delays = [logo], [100]
        image_item = canvas.create_image(size // 2, size // 2, image=logo, tags=("orb",))
        status_dot = canvas.create_oval(size - 19, size - 19, size - 10, size - 10, fill=self._accent_color, outline="", tags=("orb",))
        name_item = canvas.create_text(size // 2, size - 12, text=self._display_name, fill=self._accent_color, font=("Segoe UI", max(7, size // 15)), tags=("orb",))

        outcome = "exit"
        state: dict[str, Any] = {
            "name": "idle", "media": "stopped", "angle": 0,
            "rotation_job": None, "logo_animation_job": None, "click_job": None, "radial_job": None,
            "dispatch_job": None, "auto_exit_job": None, "open_radial_job": None,
            "action_job": None,
            "frames": None, "frame_index": 0, "photo": logo, "logo": logo,
            "logo_frames": logo_frames, "logo_delays": logo_delays, "logo_frame_index": 0,
            "center": size // 2, "radial_open": False,
            "closing": False,
        }
        del logo
        drag = {"x": 0, "y": 0, "moved": False}
        radial_items: list[int] = []

        def orb_bounds(inset: int = 8) -> tuple[int, int, int, int]:
            center = int(state["center"])
            half = size // 2
            return center - half + inset, center - half + inset, center + half - inset, center + half - inset

        def position_orb(center: int) -> None:
            state["center"] = center
            left, top, right, bottom = orb_bounds()
            canvas.coords(ring, left, top, right, bottom)
            canvas.coords(image_item, center, center)
            canvas.coords(status_dot, right - 15, bottom - 15, right - 6, bottom - 6)
            canvas.coords(name_item, center, bottom - 8)

        def set_color(color: str, width: int = 2) -> None:
            canvas.itemconfigure(ring, outline=color, width=width)
            canvas.itemconfigure(status_dot, fill=color)

        def stop_rotation() -> None:
            job = state.get("rotation_job")
            if job is not None:
                root.after_cancel(job)
                state["rotation_job"] = None

        def stop_logo_animation() -> None:
            job = state.get("logo_animation_job")
            if job is not None:
                root.after_cancel(job)
                state["logo_animation_job"] = None

        def animate_logo() -> None:
            frames = state.get("logo_frames") or []
            if state["name"] == "music" or len(frames) < 2 or state["closing"]:
                state["logo_animation_job"] = None
                return
            state["logo_frame_index"] = (int(state["logo_frame_index"]) + 1) % len(frames)
            state["photo"] = frames[state["logo_frame_index"]]
            canvas.itemconfigure(image_item, image=state["photo"])
            delays = state.get("logo_delays") or [100]
            delay = delays[min(state["logo_frame_index"], len(delays) - 1)]
            state["logo_animation_job"] = root.after(delay, animate_logo)

        def rotate_art() -> None:
            frames = state["frames"]
            if state["name"] != "music" or not frames:
                state["rotation_job"] = None
                return
            state["frame_index"] = (state["frame_index"] + 1) % len(frames)
            state["photo"] = frames[state["frame_index"]]
            canvas.itemconfigure(image_item, image=state["photo"])
            state["rotation_job"] = root.after(125, rotate_art)

        def set_state(name: str) -> None:
            stop_rotation()
            state["name"] = name
            if name in {"music", "paused"} and state.get("frames"):
                stop_logo_animation()
            elif len(state.get("logo_frames") or []) > 1 and state.get("logo_animation_job") is None:
                animate_logo()
            colors = {
                "listening": "#ff2a6d", "thinking": "#ffcc33", "speaking": "#00f3ff",
                "music": "#00ff88", "paused": "#00a868", "error": "#ff2a6d",
            }
            # Personalization owns the ring/radial color. Runtime state is shown
            # by the small dot so playback never silently overwrites user color.
            canvas.itemconfigure(ring, outline=self._accent_color, width=3 if name in {"listening", "speaking", "music"} else 2)
            canvas.itemconfigure(status_dot, fill=colors.get(name, self._accent_color))
            if name == "music" and state["frames"]:
                rotate_art()

        def show_logo() -> None:
            stop_rotation()
            state["frames"] = None
            state["logo_frame_index"] = 0
            state["photo"] = (state.get("logo_frames") or [state["logo"]])[0]
            canvas.itemconfigure(image_item, image=state["photo"])
            if len(state.get("logo_frames") or []) > 1 and state.get("logo_animation_job") is None:
                animate_logo()

        def show_art(artwork_url: str | None) -> None:
            if not artwork_url or not self._show_album_art:
                show_logo()
                return
            artwork_id = artwork_id_from_url(artwork_url)
            resource = self._artwork(artwork_id) if artwork_id else None
            if resource is None:
                show_logo()
                return
            try:
                from PIL import Image, ImageDraw, ImageOps, ImageTk

                image = Image.open(BytesIO(resource[1])).convert("RGBA")
                edge = max(48, size - 20)
                image = ImageOps.fit(image, (edge, edge), method=Image.Resampling.LANCZOS)
                mask = Image.new("L", image.size, 0)
                ImageDraw.Draw(mask).ellipse((0, 0, image.width - 1, image.height - 1), fill=255)
                image.putalpha(mask)
                state["frames"] = [
                    ImageTk.PhotoImage(
                        image.rotate(-angle, resample=Image.Resampling.BILINEAR), master=root
                    )
                    for angle in range(0, 360, 15)
                ]
                state["frame_index"] = 0
                state["photo"] = state["frames"][0]
                canvas.itemconfigure(image_item, image=state["photo"])
            except Exception:
                show_logo()

        def apply_event(event: Event) -> None:
            nonlocal outcome
            event_type = event.type
            payload = event.payload or {}
            if event_type == "ui.window.main":
                outcome = "main"
                root.quit()
            elif event_type == "ui.window.exit":
                root.quit()
            elif event_type == "music.started":
                state["media"] = "playing"
                show_art(str(payload.get("artwork_url")) if payload.get("artwork_url") else None)
                set_state("music")
            elif event_type == "music.paused":
                state["media"] = "paused"
                set_state("paused")
            elif event_type == "music.resumed":
                state["media"] = "playing"
                set_state("music")
            elif event_type == "music.stopped":
                state["media"] = "stopped"
                show_logo()
                set_state("idle")
            elif event_type == "speech.listening.started":
                set_state("listening")
            elif event_type == "speech.audio.level" and state["name"] == "listening":
                level = max(0.0, min(1.0, float(payload.get("level", 0))))
                inset = max(1, 4 - round(level * 3))
                canvas.coords(ring, *orb_bounds(inset))
            elif event_type in {"speech.transcription.started", "assistant.processing.started"}:
                set_state("thinking")
            elif event_type == "assistant.speaking.started":
                set_state("speaking")
            elif event_type in {"voice.cycle.completed", "voice.cycle.cancelled", "assistant.speaking.ended"}:
                set_state("music" if state["media"] == "playing" else ("paused" if state["media"] == "paused" else "idle"))
            elif event_type == "voice.cycle.error":
                set_state("error")

        def invoke(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            result = self._action(action, payload or {})
            if not result.get("ok"):
                set_state("error")
            return result

        def toggle_media() -> None:
            if state["media"] == "playing":
                invoke("media.pause")
            elif state["media"] == "paused":
                invoke("media.resume")
            else:
                invoke("media.play")

        def expand(view: str = "main") -> None:
            nonlocal outcome
            outcome = view
            root.quit()

        def cancel_radial_job() -> None:
            job = state.get("radial_job")
            if job is not None:
                root.after_cancel(job)
                state["radial_job"] = None

        def radial_window(edge: int, screen_center: tuple[int, int]) -> None:
            left = round(screen_center[0] - edge / 2)
            top = round(screen_center[1] - edge / 2)
            root.geometry(f"{edge}x{edge}+{left}+{top}")
            canvas.configure(width=edge, height=edge)
            position_orb(edge // 2)

        def delete_radial_items() -> None:
            while radial_items:
                canvas.delete(radial_items.pop())

        def close_radial(*, immediate: bool = False) -> None:
            if not state["radial_open"] and not radial_items:
                return
            cancel_radial_job()
            state["radial_open"] = False
            current_center = (
                root.winfo_x() + int(state["center"]),
                root.winfo_y() + int(state["center"]),
            )
            screen_center = state.pop("radial_origin", current_center)
            nodes = list(state.get("radial_nodes") or [])
            tooltip = state.get("radial_tooltip")

            def finish() -> None:
                delete_radial_items()
                state["radial_nodes"] = []
                state["radial_tooltip"] = None
                radial_window(size, screen_center)
                state["radial_job"] = None

            if immediate or not nodes:
                finish()
                return

            center = float(state["center"])
            total_steps = 6

            def collapse(step: int = 0) -> None:
                progress = min(1.0, step / total_steps)
                for node in nodes:
                    x = node["x"] + (center - node["x"]) * progress
                    y = node["y"] + (center - node["y"]) * progress
                    half = node["half"] * (1.0 - progress * 0.45)
                    canvas.coords(node["line"], center, center, x, y)
                    canvas.coords(node["circle"], x - half, y - half, x + half, y + half)
                    canvas.coords(node["icon"], x, y)
                if tooltip is not None:
                    canvas.itemconfigure(tooltip, state="hidden")
                if step >= total_steps:
                    finish()
                else:
                    state["radial_job"] = root.after(18, collapse, step + 1)

            collapse()

        def launcher_menu(category: str, x: int, y: int) -> None:
            # Refresh only known launcher sources when opening the panel. This is
            # bounded and removes stale manifests without scanning arbitrary disks.
            result = invoke("launcher.list", {"category": category, "force": True})
            old_panel = state.get("launcher_panel")
            if old_panel is not None:
                try:
                    old_panel.destroy()
                except tk.TclError:
                    pass
            panel = tk.Toplevel(root, class_="ARCHEONGhostLauncher")
            state["launcher_panel"] = panel
            panel.title("ARCHEON Launcher")
            panel.configure(bg="#071015")
            panel.attributes("-topmost", True)
            panel.transient(root)
            panel.overrideredirect(True)
            width, height = 350, 430
            left = max(8, min(root.winfo_screenwidth() - width - 8, x - width // 2))
            top = max(8, min(root.winfo_screenheight() - height - 8, y - 30))
            panel.geometry(f"{width}x{height}+{left}+{top}")
            panel.minsize(300, 280)
            header = tk.Frame(panel, bg="#071015")
            header.pack(fill="x", padx=15, pady=(14, 8))
            titles = {"app": "Aplicaciones", "game": "Juegos", "favorites": "Favoritos"}
            tk.Label(header, text=titles.get(category, "Launcher"), bg="#071015", fg="#00e5f5", font=("Segoe UI", 14, "bold")).pack(side="left")
            def dismiss_panel() -> None:
                if state.get("launcher_panel") is panel:
                    state["launcher_panel"] = None
                try:
                    panel.destroy()
                except tk.TclError:
                    pass

            tk.Button(header, text="×", command=dismiss_panel, bg="#071015", fg="#d6e8ec", activebackground="#11242c", activeforeground="#ffffff", bd=0, font=("Segoe UI", 15), cursor="hand2").pack(side="right")
            body = tk.Frame(panel, bg="#071015")
            body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
            items = result.get("items", [])[:18]
            if not items:
                tk.Label(body, text="No hay elementos en esta sección.", bg="#071015", fg="#82949a", font=("Segoe UI", 10)).pack(pady=30)
            for item in items:
                label = f"{'🎮' if item.get('kind') == 'game' else '▦'}  {item.get('name', '')}"
                button = tk.Button(
                    body, text=label, anchor="w",
                    command=lambda item_id=item.get("id"): (invoke("launcher.open", {"id": item_id}), dismiss_panel()),
                    bg="#0c171d", fg="#e8f8fa", activebackground="#12313a", activeforeground="#ffffff",
                    relief="flat", bd=0, padx=12, pady=8, font=("Segoe UI", 10), cursor="hand2",
                )
                button.pack(fill="x", pady=2)
            panel.bind("<Escape>", lambda _event: dismiss_panel())
            def close_after_focus_loss() -> None:
                try:
                    focused = panel.focus_get()
                    if focused is None or (focused is not panel and not str(focused).startswith(str(panel))):
                        dismiss_panel()
                except tk.TclError:
                    pass
            panel.bind("<FocusOut>", lambda _event: panel.after(90, close_after_focus_loss))
            panel.after_idle(lambda: (panel.focus_force(), panel.lift()))

        def volume(delta: float) -> None:
            current = self._media_status()
            invoke("media.volume", {"volume": max(0.0, min(1.0, float(current.get("volume", 0.7)) + delta))})

        def compact_settings(x: int, y: int) -> None:
            result = invoke("settings.get")
            settings = result.get("settings", {}) if result.get("ok") else {}
            old_panel = state.get("settings_panel")
            if old_panel is not None:
                try:
                    old_panel.destroy()
                except tk.TclError:
                    pass
            panel = tk.Toplevel(root, class_="ARCHEONGhostSettings")
            state["settings_panel"] = panel
            panel.configure(bg="#071015");panel.attributes("-topmost", True);panel.transient(root);panel.overrideredirect(True)
            width, height = 360, 390
            left = max(8, min(root.winfo_screenwidth() - width - 8, x - width // 2))
            top = max(8, min(root.winfo_screenheight() - height - 8, y - 30))
            panel.geometry(f"{width}x{height}+{left}+{top}")
            header = tk.Frame(panel, bg="#071015");header.pack(fill="x", padx=15, pady=(14, 8))
            tk.Label(header, text="Configuración rápida", bg="#071015", fg=self._accent_color, font=("Segoe UI", 14, "bold")).pack(side="left")
            def dismiss() -> None:
                if state.get("settings_panel") is panel:
                    state["settings_panel"] = None
                try:
                    panel.destroy()
                except tk.TclError:
                    pass
            tk.Button(header, text="×", command=dismiss, bg="#071015", fg="#d6e8ec", activebackground="#11242c", bd=0, font=("Segoe UI", 15)).pack(side="right")
            body = tk.Frame(panel, bg="#071015");body.pack(fill="both", expand=True, padx=16, pady=(4, 14))
            media = settings.get("media", {})
            volume_value = tk.IntVar(value=int(media.get("preferred_volume", 70)))
            dj_value = tk.BooleanVar(value=bool(media.get("dj_mode", False)))
            tk.Label(body, text="Música", anchor="w", bg="#071015", fg="#e8f8fa", font=("Segoe UI", 11, "bold")).pack(fill="x", pady=(2, 6))
            tk.Label(body, text="Volumen preferido", anchor="w", bg="#071015", fg="#9eb2b8", font=("Segoe UI", 9)).pack(fill="x")
            tk.Scale(body, from_=0, to=100, orient="horizontal", variable=volume_value, bg="#071015", fg="#d6e8ec", troughcolor="#16313a", highlightthickness=0, activebackground=self._accent_color).pack(fill="x")
            tk.Checkbutton(body, text="Modo DJ · continuar música relacionada", variable=dj_value, bg="#071015", fg="#d6e8ec", selectcolor="#10252c", activebackground="#071015", activeforeground="#ffffff").pack(fill="x", pady=9)
            message = tk.Label(body, text="", anchor="w", bg="#071015", fg="#9eb2b8", font=("Segoe UI", 9));message.pack(fill="x", pady=4)
            def save() -> None:
                saved = invoke("settings.update", {"changes": {"media": {"alternative_versions": media.get("alternative_versions", "ask"), "preferred_volume": volume_value.get(), "dj_mode": dj_value.get()}}})
                message.configure(text="Cambios guardados." if saved.get("ok") else "No pude guardar los cambios.")
            tk.Button(body, text="Guardar", command=save, bg=self._accent_color, fg="#001014", activebackground=self._accent_color, relief="flat", bd=0, pady=9, font=("Segoe UI", 10, "bold")).pack(fill="x", pady=(8, 5))
            tk.Button(body, text="Abrir configuración completa", command=lambda: (dismiss(), expand("settings")), bg="#0c171d", fg="#d6e8ec", activebackground="#12313a", relief="flat", bd=0, pady=9).pack(fill="x")
            panel.bind("<Escape>", lambda _event: dismiss())
            def close_after_focus_loss() -> None:
                try:
                    focused = panel.focus_get()
                    if focused is None or (focused is not panel and not str(focused).startswith(str(panel))):
                        dismiss()
                except tk.TclError:
                    pass
            panel.bind("<FocusOut>", lambda _event: panel.after(90, close_after_focus_loss))
            panel.after_idle(lambda: (panel.focus_force(), panel.lift()))

        def compact_music(x: int, y: int) -> None:
            current = self._media_status()
            old_panel = state.get("music_panel")
            if old_panel is not None:
                try:
                    old_panel.destroy()
                except tk.TclError:
                    pass
            panel = tk.Toplevel(root, class_="ARCHEONGhostMusic")
            state["music_panel"] = panel
            panel.configure(bg="#071015");panel.attributes("-topmost", True);panel.transient(root);panel.overrideredirect(True)
            width, height = 370, 300
            left = max(8, min(root.winfo_screenwidth() - width - 8, x - width // 2))
            top = max(8, min(root.winfo_screenheight() - height - 8, y - 30))
            panel.geometry(f"{width}x{height}+{left}+{top}")
            header = tk.Frame(panel, bg="#071015");header.pack(fill="x", padx=15, pady=(14, 8))
            tk.Label(header, text="Reproductor", bg="#071015", fg=self._accent_color, font=("Segoe UI", 14, "bold")).pack(side="left")
            def dismiss() -> None:
                if state.get("music_panel") is panel:
                    state["music_panel"] = None
                try:
                    panel.destroy()
                except tk.TclError:
                    pass
            tk.Button(header, text="×", command=dismiss, bg="#071015", fg="#d6e8ec", activebackground="#11242c", bd=0, font=("Segoe UI", 15)).pack(side="right")
            body = tk.Frame(panel, bg="#071015");body.pack(fill="both", expand=True, padx=16, pady=(4, 14))
            track = current.get("track") or {}
            title = str(track.get("title") or "Sin reproducción activa")
            artist = str(track.get("artist") or "")
            tk.Label(body, text=title, anchor="w", bg="#071015", fg="#f2fdff", font=("Segoe UI", 11, "bold"), wraplength=330).pack(fill="x")
            tk.Label(body, text=artist, anchor="w", bg="#071015", fg="#9eb2b8", font=("Segoe UI", 9)).pack(fill="x", pady=(2, 12))
            controls = tk.Frame(body, bg="#071015");controls.pack(fill="x")
            button_options = {"bg":"#0c171d", "fg":"#e8f8fa", "activebackground":"#12313a", "activeforeground":"#ffffff", "relief":"flat", "bd":0, "width":5, "pady":8, "font":("Segoe UI Symbol", 11), "cursor":"hand2"}
            for label, command in (
                ("⏮", lambda: invoke("media.previous")),
                ("⏯", toggle_media),
                ("⏭", lambda: invoke("media.next")),
                ("■", lambda: invoke("media.stop")),
            ):
                tk.Button(controls, text=label, command=command, **button_options).pack(side="left", expand=True, padx=3)
            tk.Button(body, text="Elegir música local", command=lambda: invoke("media.choose"), bg="#0c171d", fg="#d6e8ec", activebackground="#12313a", relief="flat", bd=0, pady=9).pack(fill="x", pady=(14, 5))
            panel.bind("<Escape>", lambda _event: dismiss())
            def close_after_focus_loss() -> None:
                try:
                    focused = panel.focus_get()
                    if focused is None or (focused is not panel and not str(focused).startswith(str(panel))):
                        dismiss()
                except tk.TclError:
                    pass
            panel.bind("<FocusOut>", lambda _event: panel.after(90, close_after_focus_loss))
            panel.after_idle(lambda: (panel.focus_force(), panel.lift()))

        def show_radial() -> None:
            if state["radial_open"]:
                close_radial()
                return
            cancel_radial_job()
            action_ids = radial_action_ids(str(state["media"]))
            if "previous" in action_ids:
                actions = [
                    ("⏮", self._text["ghost.previous"], lambda *_: invoke("media.previous")),
                    ("⏯", self._text["ghost.play_pause"], lambda *_: toggle_media()),
                    ("⏭", self._text["ghost.next"], lambda *_: invoke("media.next")),
                    ("■", self._text["ghost.stop"], lambda *_: invoke("media.stop")),
                    ("−", self._text["ghost.volume_down"], lambda *_: volume(-0.1)),
                    ("+", self._text["ghost.volume_up"], lambda *_: volume(0.1)),
                    ("♫", self._text["ghost.choose_music"], lambda x, y: compact_music(x, y), True),
                    ("⚙", self._text["ghost.settings"], lambda x, y: compact_settings(x, y), True),
                    ("↗", self._text["ghost.open"], lambda *_: expand()),
                ]
            else:
                actions = [
                    ("⌂", self._text["ghost.open"], lambda *_: expand("main")),
                    ("🎙", self._text["ghost.listen"], lambda *_: invoke("voice.listen")),
                    ("▦", self._text["ghost.apps"], lambda x, y: launcher_menu("app", x, y), True),
                    ("🎮", self._text["ghost.games"], lambda x, y: launcher_menu("game", x, y), True),
                    ("★", self._text["ghost.favorites"], lambda x, y: launcher_menu("favorites", x, y), True),
                    ("⚙", self._text["ghost.settings"], lambda x, y: compact_settings(x, y), True),
                    ("＋", "Añadir atajo", lambda *_: expand("launcher-add")),
                ]
            screen_center = (root.winfo_x() + size // 2, root.winfo_y() + size // 2)
            state["radial_origin"] = screen_center
            expanded_edge = max(300, size * 3)
            display_center = (
                max(expanded_edge // 2, min(root.winfo_screenwidth() - expanded_edge // 2, screen_center[0])),
                max(expanded_edge // 2, min(root.winfo_screenheight() - expanded_edge // 2, screen_center[1])),
            )
            radial_window(expanded_edge, display_center)
            center = float(expanded_edge // 2)
            radius = min(expanded_edge * 0.36, center - 28)
            half = max(18.0, min(23.0, size * 0.22))
            targets = radial_layout(len(actions), center, radius)
            state["radial_open"] = True
            state["radial_nodes"] = []

            halo = canvas.create_oval(
                center - radius, center - radius, center + radius, center + radius,
                outline=self._accent_color, width=1, dash=(2, 5), tags=("radial",),
            )
            radial_items.append(halo)
            canvas.tag_lower(halo, "orb")
            tooltip = canvas.create_text(
                center, min(expanded_edge - 14, center + radius + 25), text="",
                fill="#b9faff", font=("Segoe UI", 9, "bold"), state="hidden",
                tags=("radial",),
            )
            radial_items.append(tooltip)
            state["radial_tooltip"] = tooltip

            def activate(callback, event, keep_radial: bool = False) -> None:
                x_root, y_root = event.x_root, event.y_root
                if keep_radial:
                    callback(x_root, y_root)
                    return
                close_radial()
                def run_action() -> None:
                    state["action_job"] = None
                    callback(x_root, y_root)
                state["action_job"] = root.after(135, run_action)

            def hover(node, active: bool) -> None:
                canvas.itemconfigure(
                    node["circle"],
                    fill="#0b313b" if active else "#071a21",
                    outline="#ffffff" if active else self._accent_color,
                    width=3 if active else 2,
                )
                canvas.itemconfigure(tooltip, text=node["label"], state="normal" if active else "hidden")

            for index, (action, (target_x, target_y)) in enumerate(zip(actions, targets)):
                icon, label, callback = action[:3]
                keep_radial = bool(action[3]) if len(action) > 3 else False
                tag = f"radial-action-{index}"
                line = canvas.create_line(center, center, center, center, fill=self._accent_color, width=0, state="hidden", tags=("radial",))
                circle = canvas.create_oval(center - half, center - half, center + half, center + half, fill="#071a21", outline=self._accent_color, width=2, tags=("radial", tag))
                icon_item = canvas.create_text(center, center, text=icon, fill="#e5ffff", font=("Segoe UI Symbol", max(10, round(half * 0.72)), "bold"), tags=("radial", tag))
                radial_items.extend((line, circle, icon_item))
                node = {"line": line, "circle": circle, "icon": icon_item, "x": target_x, "y": target_y, "half": half, "label": label}
                state["radial_nodes"].append(node)
                canvas.tag_bind(tag, "<Enter>", lambda _event, item=node: hover(item, True))
                canvas.tag_bind(tag, "<Leave>", lambda _event, item=node: hover(item, False))
                canvas.tag_bind(tag, "<ButtonRelease-1>", lambda event, cb=callback, keep=keep_radial: activate(cb, event, keep))

            total_steps = 8

            def unfold(step: int = 0) -> None:
                progress = min(1.0, step / total_steps)
                eased = 1.0 - (1.0 - progress) ** 3
                for node in state["radial_nodes"]:
                    x = center + (node["x"] - center) * eased
                    y = center + (node["y"] - center) * eased
                    canvas.coords(node["line"], center, center, x, y)
                    canvas.coords(node["circle"], x - half, y - half, x + half, y + half)
                    canvas.coords(node["icon"], x, y)
                if step >= total_steps:
                    state["radial_job"] = None
                else:
                    state["radial_job"] = root.after(18, unfold, step + 1)

            unfold()

        menu = tk.Menu(root, tearoff=False)

        def show_context_menu(event) -> None:
            menu.delete(0, "end")
            if state["media"] in {"playing", "paused"}:
                menu.add_command(label=self._text["ghost.play_pause"], command=toggle_media)
                menu.add_command(label=self._text["ghost.previous"], command=lambda: invoke("media.previous"))
                menu.add_command(label=self._text["ghost.next"], command=lambda: invoke("media.next"))
                menu.add_command(label=self._text["ghost.stop"], command=lambda: invoke("media.stop"))
                menu.add_separator()
            menu.add_command(label=self._text["ghost.open"], command=expand)
            menu.add_command(label=self._text["ghost.listen"], command=lambda: invoke("voice.listen"))
            menu.add_command(label=self._text["ghost.apps"], command=lambda: launcher_menu("app", event.x_root, event.y_root))
            menu.add_command(label=self._text["ghost.games"], command=lambda: launcher_menu("game", event.x_root, event.y_root))
            menu.add_command(label=self._text["ghost.settings"], command=lambda: compact_settings(event.x_root, event.y_root))
            menu.add_separator()
            menu.add_command(label=self._text["ghost.exit"], command=lambda: invoke("app.exit"))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        def begin_drag(event) -> None:
            drag.update(x=event.x_root, y=event.y_root, moved=False)

        def move(event) -> None:
            dx, dy = event.x_root - drag["x"], event.y_root - drag["y"]
            if abs(dx) + abs(dy) > 2:
                drag["moved"] = True
            root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")
            drag["x"], drag["y"] = event.x_root, event.y_root

        def delayed_radial() -> None:
            state["click_job"] = None
            show_radial()

        def release(_event) -> None:
            if not drag["moved"]:
                if state["click_job"] is not None:
                    root.after_cancel(state["click_job"])
                state["click_job"] = root.after(220, delayed_radial)

        def double_click(_event) -> None:
            if state["click_job"] is not None:
                root.after_cancel(state["click_job"])
                state["click_job"] = None
            expand()

        canvas.tag_bind("orb", "<ButtonPress-1>", begin_drag)
        canvas.tag_bind("orb", "<B1-Motion>", move)
        canvas.tag_bind("orb", "<ButtonRelease-1>", release)
        canvas.tag_bind("orb", "<Double-Button-1>", double_click)
        canvas.tag_bind("orb", "<Button-3>", show_context_menu)

        current_media = self._media_status()
        if current_media.get("state") in {"playing", "paused"}:
            track = current_media.get("track") or {}
            state["media"] = str(current_media["state"])
            show_art(track.get("artwork_url"))
            set_state("music" if state["media"] == "playing" else "paused")

        subscription = self._events.subscribe("*", max_queue=64)

        def drain_events() -> None:
            state["dispatch_job"] = None
            if state["closing"]:
                return
            for _ in range(32):
                try:
                    event = subscription.get(timeout=0)
                except Empty:
                    break
                except RuntimeError:
                    return
                apply_event(event)
                if state["closing"]:
                    return
            state["dispatch_job"] = root.after(25, drain_events)

        state["dispatch_job"] = root.after(0, drain_events)
        if len(state.get("logo_frames") or []) > 1:
            state["logo_animation_job"] = root.after(
                (state.get("logo_delays") or [100])[0], animate_logo,
            )
        if open_radial:
            def open_initial_radial() -> None:
                state["open_radial_job"] = None
                show_radial()
            state["open_radial_job"] = root.after(350, open_initial_radial)
        if auto_exit_seconds is not None:
            state["auto_exit_job"] = root.after(max(1, int(auto_exit_seconds * 1000)), root.quit)
        try:
            root.mainloop()
        finally:
            state["closing"] = True
            for job_name in (
                "dispatch_job", "auto_exit_job", "open_radial_job", "action_job", "click_job",
                "logo_animation_job",
            ):
                job = state.get(job_name)
                if job is not None:
                    try:
                        root.after_cancel(job)
                    except tk.TclError:
                        pass
                    state[job_name] = None
            close_radial(immediate=True)
            stop_rotation()
            self._config.position_x = root.winfo_x()
            self._config.position_y = root.winfo_y()
            subscription.close()
            canvas.itemconfigure(image_item, image="")
            image_names: set[str] = set()
            for value in (
                state.get("photo"), state.get("logo"),
                *(state.get("frames") or []), *(state.get("logo_frames") or []),
            ):
                if value is not None:
                    image_names.add(str(value))
            for image_name in image_names:
                try:
                    root.tk.call("image", "delete", image_name)
                except tk.TclError:
                    pass
            state["frames"] = None
            state["photo"] = None
            state["logo"] = None
            state["logo_frames"] = None
            gc.collect()
            launcher_panel = state.get("launcher_panel")
            if launcher_panel is not None:
                try:
                    launcher_panel.destroy()
                except tk.TclError:
                    pass
            settings_panel = state.get("settings_panel")
            if settings_panel is not None:
                try:
                    settings_panel.destroy()
                except tk.TclError:
                    pass
            music_panel = state.get("music_panel")
            if music_panel is not None:
                try:
                    music_panel.destroy()
                except tk.TclError:
                    pass
            try:
                menu.destroy()
                root.update_idletasks()
                root.destroy()
            except tk.TclError:
                pass
        return outcome
