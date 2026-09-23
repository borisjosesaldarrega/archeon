"""ARCHI desktop observation and control providers."""

from .engine import (
    DesktopAgentEngine, INVOKE_MANIFEST, LIST_WINDOWS_MANIFEST, LOCATE_MANIFEST,
    OBSERVE_ACTIVE_MANIFEST, TYPE_TEXT_MANIFEST, WINDOW_ACTION_MANIFEST,
)
from .windows import WindowInfo, WindowsDesktopController, WindowsDesktopObserver

__all__ = [
    "DesktopAgentEngine", "INVOKE_MANIFEST", "LIST_WINDOWS_MANIFEST", "LOCATE_MANIFEST",
    "OBSERVE_ACTIVE_MANIFEST", "TYPE_TEXT_MANIFEST", "WINDOW_ACTION_MANIFEST",
    "WindowInfo", "WindowsDesktopController", "WindowsDesktopObserver",
]
