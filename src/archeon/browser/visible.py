"""Visible browser window adapter for low-risk Computer Use tasks."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from archeon.desktop.windows import WindowsDesktopController, WindowsDesktopObserver


class VisibleBrowserSession:
    """Own one isolated Edge window with accessibility forced on.

    This adapter has no idle watcher.  It starts only for an explicit visible
    browser task and exposes the page through Chromium's accessibility tree.
    """

    def __init__(self) -> None:
        self.observer = WindowsDesktopObserver(max_elements=500, max_depth=32)
        self.window_handle = 0
        self._profile: Path | None = None
        self._process: subprocess.Popen[bytes] | None = None

    @staticmethod
    def _edge_path() -> Path:
        candidates = (
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        )
        edge = next((item for item in candidates if item.is_file()), None)
        if edge is None:
            raise FileNotFoundError("supported_visible_browser_not_found")
        return edge

    def open(self, url: str, *, timeout_seconds: float = 15.0) -> dict[str, Any]:
        if not url.startswith("https://"):
            raise ValueError("https_url_required")
        before = {item.handle for item in self.observer.find_windows(process_name="msedge.exe", limit=100)}
        self._profile = Path(tempfile.mkdtemp(prefix="archeon-visible-browser-"))
        self._process = subprocess.Popen(
            [
                str(self._edge_path()), "--force-renderer-accessibility", "--new-window",
                "--no-first-run", "--no-default-browser-check", "--guest",
                "--disable-sync", "--disable-signin-promo",
                "--disable-features=msEdgeFirstRunExperience",
                f"--user-data-dir={self._profile}", url,
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + max(2.0, min(float(timeout_seconds), 45.0))
        selected = None
        while time.monotonic() < deadline:
            windows = self.observer.find_windows(process_name="msedge.exe", limit=100)
            selected = next((item for item in windows if item.handle not in before), None)
            if selected and selected.title and "new tab" not in selected.title.casefold():
                break
            time.sleep(0.12)
        if selected is None:
            self.close()
            raise TimeoutError("visible_browser_window_timeout")
        self.window_handle = selected.handle
        WindowsDesktopController._focus_window(selected.handle)
        evidence: dict[str, Any] = {}
        root_seen = False
        interactive_ready = False
        while time.monotonic() < deadline:
            time.sleep(0.18)
            evidence = self.observer.observe_active(include_screenshot_hash=False)
            root_seen = any(
                item.get("automation_id") == "RootWebArea" or item.get("control_type") == 50030
                for item in evidence.get("elements", [])
            )
            interactive_ready = any(
                str(item.get("name", "")).casefold() in {"buscar", "search"}
                and item.get("bounds", [0, 0, 0, 0])[2] > item.get("bounds", [0, 0, 0, 0])[0]
                for item in evidence.get("elements", [])
            )
            if root_seen and interactive_ready:
                break
        return {
            "url": url, "window": evidence["window"], "application": evidence["application"],
            "structured_interface": "chromium_accessibility_tree",
            "page_root_seen": root_seen, "element_count": evidence["element_count"],
            "interactive_ready": interactive_ready,
            "changed_state": True,
        }

    def verify_search_results(self, query: str) -> dict[str, Any]:
        deadline = time.monotonic() + 12.0
        evidence: dict[str, Any] = {}
        query_key = " ".join(query.casefold().split())
        while time.monotonic() < deadline:
            if self.window_handle:
                WindowsDesktopController._focus_window(self.window_handle)
                time.sleep(0.08)
            evidence = self.observer.observe_active(include_screenshot_hash=False)
            window = evidence.get("window", {})
            if self.window_handle and int(window.get("handle", 0)) != self.window_handle:
                time.sleep(0.2)
                continue
            title = str(window.get("title", ""))
            names = [str(item.get("name", "")) for item in evidence.get("elements", [])]
            query_visible = query_key in title.casefold() or any(query_key in name.casefold() for name in names)
            result_controls = self._youtube_result_elements(evidence.get("elements", []))
            if query_visible and result_controls:
                return {
                    "window": window, "application": evidence.get("application", {}),
                    "page_type": "search_results", "search_query": query,
                    "query_visible": True, "visible_result_controls": len(result_controls),
                    "result_count": len(result_controls),
                    "result_samples": [str(item.get("name", ""))[:180] for item in result_controls[:3]],
                    "perception_method": "browser_accessibility_tree", "verified": True,
                }
            time.sleep(0.2)
        return {
            "window": evidence.get("window", {}), "application": evidence.get("application", {}),
            "page_type": "unknown", "search_query": query, "query_visible": False,
            "visible_result_controls": 0, "result_count": 0, "result_samples": [],
            "perception_method": "browser_accessibility_tree",
            "verified": False,
        }

    @staticmethod
    def _youtube_result_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return actual YouTube result items, never generic page chrome.

        The earlier verifier counted every button/link/text control, so the
        search bar and navigation could falsely satisfy "results visible".
        Chromium exposes stable accessibility markers for video and Shorts
        result endpoints; require one of those markers instead.
        """
        output: list[dict[str, Any]] = []
        for item in elements:
            automation_id = str(item.get("automation_id", "")).casefold()
            class_name = str(item.get("class_name", "")).casefold()
            name = str(item.get("name", "")).strip()
            is_video = automation_id == "video-title" and "ytd-video-renderer" in class_name
            is_short = "shortslockupviewmodelhostendpoint" in class_name
            if name and item.get("control_type") == 50005 and (is_video or is_short):
                output.append(item)
        return output

    def locate_search(self) -> dict[str, Any]:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if self.window_handle:
                WindowsDesktopController._focus_window(self.window_handle)
                time.sleep(0.08)
            evidence = self.observer.observe_active(include_screenshot_hash=False)
            candidates = [
                item for item in evidence.get("elements", [])
                if str(item.get("name", "")).casefold() in {"buscar", "search"}
                and item.get("control_type") in {50003, 50004, 50030}
                and item.get("bounds", [0, 0, 0, 0])[2] > item.get("bounds", [0, 0, 0, 0])[0]
            ]
            if candidates:
                target = candidates[0]
                return {
                    "element": target["name"], "bounds": target["bounds"],
                    "enabled": target["enabled"], "control_type": target["control_type"],
                    "window": evidence["window"], "application": evidence["application"],
                    "perception_method": "browser_accessibility_tree", "changed_state": False,
                }
            time.sleep(0.15)
        raise LookupError("visible_browser_search_not_found")

    def close(self) -> None:
        if self.window_handle:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if user32.IsWindow(self.window_handle):
                user32.PostMessageW(self.window_handle, 0x0010, 0, 0)
            self.window_handle = 0
        if self._process is not None:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            self._process = None
        if self._profile is not None:
            time.sleep(0.15)
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = None
