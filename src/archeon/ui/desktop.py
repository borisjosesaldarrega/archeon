"""Optional WebView2 desktop host with a real independent Ghost window."""

from __future__ import annotations

from queue import Empty
from threading import Event as ThreadEvent
from threading import Thread, Timer

from archeon.core.config import AppConfig
from archeon.core.events import EventBus


class DesktopUnavailable(RuntimeError):
    pass


class DesktopHost:
    def __init__(self, events: EventBus, *, base_url: str, token: str, config: AppConfig) -> None:
        self._events = events
        self._base_url = base_url
        self._token = token
        self._config = config
        self._stopping = ThreadEvent()
        self._bridge: Thread | None = None

    def run(self, *, initial_mode: str = "main", auto_exit_seconds: float | None = None) -> None:
        try:
            import webview
        except ImportError as error:
            raise DesktopUnavailable(
                "pywebview is not installed; install the `desktop` optional dependency"
            ) from error

        main_window = webview.create_window(
            "ARCHEON",
            f"{self._base_url}/?token={self._token}",
            width=1100,
            height=720,
            min_size=(760, 520),
            background_color="#05070a",
            text_select=True,
        )
        size = self._config.ghost.size
        ghost_window = webview.create_window(
            "ARCHEON Orb",
            f"{self._base_url}/ghost?token={self._token}",
            width=size,
            height=size,
            min_size=(64, 64),
            frameless=True,
            easy_drag=True,
            on_top=self._config.ghost.always_on_top,
            transparent=True,
            background_color="#000000",
            hidden=True,
            text_select=False,
        )

        def destroy_all(*_: object) -> None:
            self._stopping.set()
            for window in (ghost_window, main_window):
                try:
                    window.destroy()
                except Exception:
                    pass

        def bridge() -> None:
            subscription = self._events.subscribe("ui.window.*", max_queue=16)
            try:
                if initial_mode == "ghost":
                    main_window.hide()
                    ghost_window.show()
                while not self._stopping.is_set():
                    try:
                        event = subscription.get(timeout=0.5)
                    except Empty:
                        continue
                    if event.type == "ui.window.ghost":
                        main_window.hide()
                        ghost_window.show()
                    elif event.type == "ui.window.main":
                        ghost_window.hide()
                        main_window.show()
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

        main_window.events.closed += destroy_all
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
