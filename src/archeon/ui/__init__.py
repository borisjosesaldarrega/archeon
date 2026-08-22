"""Local event-driven user interface and optional WebView2 host."""

from .desktop import DesktopHost, DesktopUnavailable
from .server import UIServer

__all__ = ["DesktopHost", "DesktopUnavailable", "UIServer"]

