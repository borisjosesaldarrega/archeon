"""Optional WebView2 desktop host with a lazy independent Ghost window."""

from __future__ import annotations

from queue import Empty
from collections.abc import Callable
from threading import Event as ThreadEvent
from threading import Thread, Timer
from typing import Any

from archeon.core.config import AppConfig, GhostConfig
from archeon.core.events import EventBus
from archeon.core.paths import ResourceManager


class DesktopUnavailable(RuntimeError):
    pass


class DesktopHost:
    def __init__(
        self,
        events: EventBus,
        *,
        base_url: str,
        token: str,
        config: AppConfig,
        action_handler: Callable[[str, dict[str, Any]], dict[str, Any]],
        media_status_handler: Callable[[], dict[str, Any]],
        artwork_handler: Callable[[str], tuple[str, bytes] | None],
        resources: ResourceManager | None = None,
    ) -> None:
        self._events = events
        self._base_url = base_url
        self._token = token
        self._config = config
        self._action_handler = action_handler
        self._media_status_handler = media_status_handler
        self._artwork_handler = artwork_handler
        self._resources = resources
        self._stopping = ThreadEvent()
        self._bridge: Thread | None = None

    def run(
        self,
        *,
        initial_mode: str = "main",
        auto_exit_seconds: float | None = None,
        benchmark_music: bool = False,
        benchmark_guest: bool = False,
        benchmark_radial: bool = False,
    ) -> None:
        if initial_mode == "ghost":
            from archeon.ui.ghost_native import NativeGhostHost

            # ConfigurationManager swaps its snapshot after a save. Resolve the
            # latest values so Ghost shares the current logo and personalization.
            current = self._action_handler("settings.get", {})
            settings = current.get("settings", {}) if current.get("ok") else {}
            ghost_values = settings.get("ghost", {})
            current_ghost = GhostConfig(**{
                key: ghost_values.get(key, getattr(self._config.ghost, key))
                for key in GhostConfig.__dataclass_fields__
            })
            current_appearance = settings.get("appearance", {})
            current_language = settings.get("language", {})
            current_assistant = settings.get("assistant", {})
            current_media = settings.get("media", {})
            interface_layout = current_appearance.get("interface_layout", {})
            orb_layout = interface_layout.get("orb", {}) if isinstance(interface_layout, dict) else {}

            outcome = NativeGhostHost(
                self._events,
                current_ghost,
                action_handler=self._action_handler,
                media_status_handler=self._media_status_handler,
                artwork_handler=self._artwork_handler,
                locale=str(current_language.get("interface", self._config.locale)),
                display_name=str(current_assistant.get("wake_name", self._config.assistant.wake_name)),
                logo_path=current_appearance.get("logo_path", self._config.appearance.logo_path),
                logo_position_x=float(current_appearance.get("logo_position_x", 0)),
                logo_position_y=float(current_appearance.get("logo_position_y", 0)),
                logo_zoom=int(current_appearance.get("logo_zoom", 100)),
                accent_color=str(orb_layout.get("color") or current_appearance.get("accent_color") or "#00F3FF"),
                show_album_art=bool(current_media.get("show_album_art", self._config.media.show_album_art)),
                vinyl_orb=bool(current_media.get("vinyl_orb", self._config.media.vinyl_orb)),
                resources=self._resources,
            ).run(
                auto_exit_seconds=auto_exit_seconds,
                open_radial=benchmark_radial,
            )
            if outcome in {"main", "settings", "launcher", "launcher-add"}:
                # Expanding Ghost means the user's last mode is now the full
                # interface. Persist it before creating WebView so a later
                # launch does not incorrectly reopen Ghost/radial.
                self._action_handler("window.main", {})
                self.run(initial_mode=outcome, auto_exit_seconds=auto_exit_seconds)
            return
        try:
            import webview
        except ImportError as error:
            raise DesktopUnavailable(
                "pywebview is not installed; install the `desktop` optional dependency"
            ) from error

        windows: dict[str, Any] = {}
        transition_to_ghost = ThreadEvent()

        def destroy_all(*_: object) -> None:
            if self._stopping.is_set():
                return
            self._stopping.set()
            for window in tuple(windows.values()):
                try:
                    window.destroy()
                except Exception:
                    pass

        def make_main():
            window = windows.get("main")
            if window is None:
                window = webview.create_window(
                    "ARCHEON",
                    f"{self._base_url}/?token={self._token}" + (f"&view={initial_mode}" if initial_mode != "main" else ""),
                    width=1100,
                    height=720,
                    min_size=(760, 520),
                    background_color="#05070a",
                    text_select=True,
                )
                windows["main"] = window
                window.events.closed += destroy_all
                if initial_mode == "main":
                    def apply_initial_window_mode() -> None:
                        try:
                            mode = self._config.startup.window_mode
                            if self._config.startup.start_minimized or mode == "minimized":
                                window.minimize()
                            elif mode == "maximized":
                                window.maximize()
                        except Exception:
                            pass

                    window.events.loaded += apply_initial_window_mode
            return window

        def bridge() -> None:
            subscription = self._events.subscribe("ui.window.*", max_queue=16)
            try:
                while not self._stopping.is_set():
                    try:
                        event = subscription.get(timeout=0.5)
                    except Empty:
                        continue
                    if event.type == "ui.window.ghost":
                        transition_to_ghost.set()
                        destroy_all()
                    elif event.type == "ui.window.main":
                        main = make_main()
                        ghost = windows.get("ghost")
                        if ghost is not None:
                            ghost.hide()
                        main.show()
                    elif event.type == "ui.window.exit":
                        destroy_all()
            except RuntimeError:
                pass
            finally:
                subscription.close()

        timer: Timer | None = None

        def startup() -> None:
            nonlocal timer
            self._bridge = Thread(target=bridge, name="archeon-window-bridge", daemon=False)
            self._bridge.start()
            if auto_exit_seconds is not None:
                timer = Timer(auto_exit_seconds, destroy_all)
                timer.daemon = True
                timer.start()

        initial_window = make_main()
        if (benchmark_music or benchmark_guest) and initial_mode == "main":
            def benchmark_setup() -> None:
                script = "document.getElementById('guest-button').click();"
                if benchmark_music:
                    script += "setTimeout(()=>document.getElementById('music-play').click(),500);"
                initial_window.evaluate_js(script)

            initial_window.events.loaded += benchmark_setup
        try:
            webview.start(startup, gui="edgechromium", debug=False, private_mode=False)
        finally:
            self._stopping.set()
            if timer is not None:
                timer.cancel()
            if self._bridge is not None:
                self._bridge.join(timeout=3.0)
                if self._bridge.is_alive():
                    raise RuntimeError("window bridge thread did not stop")
        if transition_to_ghost.is_set():
            self._stopping.clear()
            self.run(initial_mode="ghost", auto_exit_seconds=auto_exit_seconds)
