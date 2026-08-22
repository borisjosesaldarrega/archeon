"""Optional WebView2 desktop host with a lazy independent Ghost window."""

from __future__ import annotations

from queue import Empty
from collections.abc import Callable
from threading import Event as ThreadEvent
from threading import Thread, Timer
from typing import Any

from archeon.core.config import AppConfig
from archeon.core.events import EventBus


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
    ) -> None:
        self._events = events
        self._base_url = base_url
        self._token = token
        self._config = config
        self._action_handler = action_handler
        self._media_status_handler = media_status_handler
        self._artwork_handler = artwork_handler
        self._stopping = ThreadEvent()
        self._bridge: Thread | None = None

    def run(
        self,
        *,
        initial_mode: str = "main",
        auto_exit_seconds: float | None = None,
        benchmark_music: bool = False,
    ) -> None:
        if initial_mode == "ghost":
            from archeon.ui.ghost_native import NativeGhostHost

            outcome = NativeGhostHost(
                self._events,
                self._config.ghost,
                action_handler=self._action_handler,
                media_status_handler=self._media_status_handler,
                artwork_handler=self._artwork_handler,
                locale=self._config.locale,
            ).run(
                auto_exit_seconds=auto_exit_seconds
            )
            if outcome == "main":
                self.run(initial_mode="main", auto_exit_seconds=auto_exit_seconds)
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
                    f"{self._base_url}/?token={self._token}",
                    width=1100,
                    height=720,
                    min_size=(760, 520),
                    background_color="#05070a",
                    text_select=True,
                )
                windows["main"] = window
                window.events.closed += destroy_all
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
        if benchmark_music and initial_mode == "main":
            initial_window.events.loaded += lambda: initial_window.evaluate_js(
                "document.getElementById('music-play').click()"
            )
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
