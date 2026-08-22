"""Native lightweight Ghost orb with real event and media controls."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from queue import Empty
from threading import Thread
from typing import Any

from archeon.core.config import GhostConfig
from archeon.core.events import Event, EventBus


def radial_action_ids(media_state: str) -> tuple[str, ...]:
    """Return the lightweight contextual action set without creating UI state."""
    if media_state in {"playing", "paused"}:
        return ("previous", "play_pause", "next", "volume_down", "volume_up", "choose_music", "open")
    return ("open", "listen", "apps", "games", "favorites", "settings")


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
    ) -> None:
        self._events = events
        self._config = config
        self._action = action_handler
        self._media_status = media_status_handler
        self._artwork = artwork_handler
        self._display_name = display_name.strip()[:24] or "Archeon"
        locale_path = Path(__file__).resolve().parent / "locales" / f"ghost-{locale}.json"
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
        ring = canvas.create_oval(4, 4, size - 4, size - 4, outline="#08d9ff", width=2, tags=("orb",))
        logo = tk.PhotoImage(file=str(Path(__file__).resolve().parent / "logo_asitente.png"))
        reduction = max(1, max(logo.width(), logo.height()) // max(64, size - 14))
        logo = logo.subsample(reduction, reduction)
        image_item = canvas.create_image(size // 2, size // 2, image=logo, tags=("orb",))
        status_dot = canvas.create_oval(size - 19, size - 19, size - 10, size - 10, fill="#08d9ff", outline="", tags=("orb",))
        name_item = canvas.create_text(size // 2, size - 12, text=self._display_name, fill="#b9faff", font=("Segoe UI", max(7, size // 15)), tags=("orb",))

        outcome = "exit"
        state: dict[str, Any] = {
            "name": "idle", "media": "stopped", "angle": 0,
            "rotation_job": None, "click_job": None, "radial_job": None,
            "frames": None, "frame_index": 0, "photo": logo,
            "center": size // 2, "radial_open": False,
        }
        drag = {"x": 0, "y": 0, "moved": False}
        radial_items: list[int] = []

        def orb_bounds(inset: int = 4) -> tuple[int, int, int, int]:
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
            colors = {
                "listening": "#ff2a6d", "thinking": "#ffcc33", "speaking": "#00f3ff",
                "music": "#00ff88", "paused": "#00a868", "error": "#ff2a6d",
            }
            set_color(colors.get(name, "#08d9ff"), 3 if name in {"listening", "speaking", "music"} else 2)
            if name == "music" and state["frames"]:
                rotate_art()

        def show_logo() -> None:
            stop_rotation()
            state["frames"] = None
            state["photo"] = logo
            canvas.itemconfigure(image_item, image=logo)

        def show_art(artwork_url: str | None) -> None:
            if not artwork_url:
                show_logo()
                return
            resource = self._artwork(artwork_url.rsplit("/", 1)[-1])
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
                    ImageTk.PhotoImage(image.rotate(-angle, resample=Image.Resampling.BILINEAR))
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
                set_state("idle")
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

        def expand() -> None:
            nonlocal outcome
            outcome = "main"
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
            result = invoke("launcher.list", {"category": category})
            submenu = tk.Menu(root, tearoff=False)
            for item in result.get("items", [])[:24]:
                submenu.add_command(label=str(item.get("name", "")), command=lambda item_id=item.get("id"): invoke("launcher.open", {"id": item_id}))
            if not result.get("items"):
                submenu.add_command(label="Sin elementos", state="disabled")
            submenu.tk_popup(x, y)

        def volume(delta: float) -> None:
            current = self._media_status()
            invoke("media.volume", {"volume": max(0.0, min(1.0, float(current.get("volume", 0.7)) + delta))})

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
                    ("−", self._text["ghost.volume_down"], lambda *_: volume(-0.1)),
                    ("+", self._text["ghost.volume_up"], lambda *_: volume(0.1)),
                    ("♫", self._text["ghost.choose_music"], lambda *_: invoke("media.choose")),
                    ("↗", self._text["ghost.open"], lambda *_: expand()),
                ]
            else:
                actions = [
                    ("↗", self._text["ghost.open"], lambda *_: expand()),
                    ("●", self._text["ghost.listen"], lambda *_: invoke("voice.listen")),
                    ("A", self._text["ghost.apps"], lambda x, y: launcher_menu("app", x, y)),
                    ("G", self._text["ghost.games"], lambda x, y: launcher_menu("game", x, y)),
                    ("★", self._text["ghost.favorites"], lambda x, y: launcher_menu("favorites", x, y)),
                    ("⚙", self._text["ghost.settings"], lambda *_: expand()),
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
                outline="#087d99", width=1, dash=(2, 5), tags=("radial",),
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

            def activate(callback, event) -> None:
                x_root, y_root = event.x_root, event.y_root
                close_radial()
                root.after(135, callback, x_root, y_root)

            def hover(node, active: bool) -> None:
                canvas.itemconfigure(
                    node["circle"],
                    fill="#0b313b" if active else "#071a21",
                    outline="#d9ffff" if active else "#00d9f5",
                    width=3 if active else 2,
                )
                canvas.itemconfigure(tooltip, text=node["label"], state="normal" if active else "hidden")

            for index, ((icon, label, callback), (target_x, target_y)) in enumerate(zip(actions, targets)):
                tag = f"radial-action-{index}"
                line = canvas.create_line(center, center, center, center, fill="#087d99", width=1, tags=("radial",))
                circle = canvas.create_oval(center - half, center - half, center + half, center + half, fill="#071a21", outline="#00d9f5", width=2, tags=("radial", tag))
                icon_item = canvas.create_text(center, center, text=icon, fill="#e5ffff", font=("Segoe UI Symbol", max(10, round(half * 0.72)), "bold"), tags=("radial", tag))
                radial_items.extend((line, circle, icon_item))
                node = {"line": line, "circle": circle, "icon": icon_item, "x": target_x, "y": target_y, "half": half, "label": label}
                state["radial_nodes"].append(node)
                canvas.tag_bind(tag, "<Enter>", lambda _event, item=node: hover(item, True))
                canvas.tag_bind(tag, "<Leave>", lambda _event, item=node: hover(item, False))
                canvas.tag_bind(tag, "<ButtonRelease-1>", lambda event, cb=callback: activate(cb, event))

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
        menu.add_command(label=self._text["ghost.play_pause"], command=toggle_media)
        menu.add_command(label=self._text["ghost.previous"], command=lambda: invoke("media.previous"))
        menu.add_command(label=self._text["ghost.next"], command=lambda: invoke("media.next"))
        menu.add_command(label=self._text["ghost.stop"], command=lambda: invoke("media.stop"))
        menu.add_separator()
        menu.add_command(label=self._text["ghost.open"], command=expand)
        menu.add_command(label=self._text["ghost.exit"], command=lambda: invoke("app.exit"))

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
        canvas.tag_bind("orb", "<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))

        current_media = self._media_status()
        if current_media.get("state") in {"playing", "paused"}:
            track = current_media.get("track") or {}
            state["media"] = str(current_media["state"])
            show_art(track.get("artwork_url"))
            set_state("music" if state["media"] == "playing" else "paused")

        subscription = self._events.subscribe("*", max_queue=64)

        def bridge() -> None:
            try:
                while True:
                    try:
                        event = subscription.get(timeout=1.0)
                    except Empty:
                        continue
                    root.after(0, apply_event, event)
            except RuntimeError:
                pass

        bridge_thread = Thread(target=bridge, name="archeon-ghost-bridge", daemon=False)
        bridge_thread.start()
        if open_radial:
            root.after(350, show_radial)
        if auto_exit_seconds is not None:
            root.after(max(1, int(auto_exit_seconds * 1000)), root.quit)
        try:
            root.mainloop()
        finally:
            close_radial(immediate=True)
            root.update_idletasks()
            stop_rotation()
            if state["click_job"] is not None:
                root.after_cancel(state["click_job"])
            self._config.position_x = root.winfo_x()
            self._config.position_y = root.winfo_y()
            subscription.close()
            bridge_thread.join(timeout=2.0)
            root.destroy()
        return outcome
