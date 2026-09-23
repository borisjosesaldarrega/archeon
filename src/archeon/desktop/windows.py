"""Event-free, on-demand Windows desktop observation primitives."""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class WindowInfo:
    handle: int
    title: str
    process_id: int
    process_name: str
    class_name: str
    bounds: tuple[int, int, int, int]
    visible: bool

    def public(self) -> dict[str, Any]:
        return asdict(self)


class WindowsDesktopObserver:
    """Reads the foreground window only when called; no polling or resident worker."""

    def __init__(self, *, max_elements: int = 180, max_depth: int = 8) -> None:
        self.max_elements = max(1, min(max_elements, 500))
        # Chromium's accessibility tree commonly places the web root around
        # depth 11 and useful page controls below depth 16.  The previous cap
        # silently reduced a DOM/accessibility-capable browser to its window
        # chrome.  The element budget still bounds the traversal.
        self.max_depth = max(1, min(max_depth, 32))

    def active_window(self) -> WindowInfo:
        if sys.platform != "win32":
            raise RuntimeError("desktop_observation_requires_windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        handle = int(user32.GetForegroundWindow())
        if not handle:
            raise RuntimeError("active_window_unavailable")
        return self._window_info(handle)

    def list_windows(self, *, limit: int = 100) -> list[WindowInfo]:
        if sys.platform != "win32":
            raise RuntimeError("window_management_requires_windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        windows: list[WindowInfo] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(handle: int, _parameter: int) -> bool:
            if len(windows) >= max(1, min(limit, 300)):
                return False
            if not user32.IsWindowVisible(handle) or user32.GetWindowTextLengthW(handle) <= 0:
                return True
            try:
                windows.append(self._window_info(int(handle)))
            except OSError:
                pass
            return True

        user32.EnumWindows(callback, 0)
        return windows

    def find_windows(
        self, *, title: str = "", process_name: str = "", exact: bool = False, limit: int = 20,
    ) -> list[WindowInfo]:
        title_query = " ".join(title.casefold().split())
        process_query = process_name.casefold().strip()
        matches: list[WindowInfo] = []
        for window in self.list_windows(limit=300):
            normalized_title = " ".join(window.title.casefold().split())
            title_matches = not title_query or (
                normalized_title == title_query if exact else title_query in normalized_title
            )
            process_matches = not process_query or window.process_name.casefold() == process_query
            if title_matches and process_matches:
                matches.append(window)
                if len(matches) >= max(1, min(limit, 100)):
                    break
        return matches

    def wait_for_window(
        self, *, title: str = "", process_name: str = "", timeout_seconds: float = 10.0,
    ) -> WindowInfo:
        deadline = time.monotonic() + max(0.1, min(timeout_seconds, 120.0))
        while time.monotonic() < deadline:
            matches = self.find_windows(title=title, process_name=process_name, limit=1)
            if matches:
                return matches[0]
            time.sleep(0.1)
        raise TimeoutError("window_wait_timeout")

    @staticmethod
    def wait_until_closed(handle: int, *, timeout_seconds: float = 10.0) -> bool:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        deadline = time.monotonic() + max(0.1, min(timeout_seconds, 120.0))
        while time.monotonic() < deadline:
            if not user32.IsWindow(handle):
                return True
            time.sleep(0.1)
        return not bool(user32.IsWindow(handle))

    def observe_active(self, *, include_screenshot_hash: bool = True) -> dict[str, Any]:
        window = self.active_window()
        elements, provider_error = self._accessible_elements(window.handle)
        application = self.classify_window(window)
        evidence: dict[str, Any] = {
            "window": window.public(),
            "application": application,
            "elements": elements,
            "element_count": len(elements),
            "provider": "windows_ui_automation" if not provider_error else "win32_window",
        }
        if provider_error:
            evidence["provider_error"] = provider_error
        if include_screenshot_hash or not elements:
            visual = self._visual_fingerprint(window.bounds)
            if visual:
                evidence["visual"] = visual
        evidence["state_hash"] = self._state_hash(evidence)
        return evidence

    @staticmethod
    def classify_window(window: WindowInfo) -> dict[str, Any]:
        """Classify a verified HWND without relying on its title alone."""
        process = window.process_name.casefold()
        class_name = window.class_name.casefold()
        if process in {"msedge.exe", "chrome.exe", "opera.exe", "brave.exe", "firefox.exe"}:
            kind, confidence, interface = "browser", 0.99, "browser_accessibility"
        elif process == "explorer.exe" and class_name == "cabinetwclass":
            kind, confidence, interface = "file_explorer", 0.99, "windows_ui_automation"
        elif process in {"notepad.exe", "wordpad.exe"}:
            kind, confidence, interface = "native_windows_app", 0.99, "windows_ui_automation"
        elif process in {"windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe"}:
            kind, confidence, interface = "terminal", 0.99, "terminal_adapter"
        elif process in {"archeon.exe", "python.exe", "pythonw.exe"} and "archeon" in window.title.casefold():
            kind, confidence, interface = "webview", 0.94, "application_api"
        elif class_name in {"#32770", "credential dialog xaml host"}:
            kind, confidence, interface = "dialog", 0.92, "windows_ui_automation"
        else:
            kind, confidence, interface = "unknown", 0.45, "windows_ui_automation"
        return {
            "name": window.process_name.removesuffix(".exe") or "Unknown",
            "process": window.process_name,
            "window_title": window.title,
            "window_handle": window.handle,
            "application_type": kind,
            "confidence": confidence,
            "available_control_method": interface,
        }

    @staticmethod
    def capture_window(
        bounds: tuple[int, int, int, int], destination: str | Path,
    ) -> dict[str, Any]:
        """Persist one explicitly requested diagnostic capture; never loops."""
        from PIL import ImageGrab

        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=bounds, all_screens=True)
        image.save(target)
        return {
            "path": str(target), "width": image.width, "height": image.height,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "temporary": False, "continuous_capture": False,
        }

    def _window_info(self, handle: int) -> WindowInfo:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        length = int(user32.GetWindowTextLengthW(handle))
        title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(handle, title_buffer, len(title_buffer))
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, class_buffer, len(class_buffer))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return WindowInfo(
            handle=handle,
            title=title_buffer.value,
            process_id=int(process_id.value),
            process_name=self._process_name(int(process_id.value)),
            class_name=class_buffer.value,
            bounds=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            visible=bool(user32.IsWindowVisible(handle)),
        )

    @staticmethod
    def _process_name(process_id: int) -> str:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process = kernel32.OpenProcess(0x1000, False, process_id)
        if not process:
            return ""
        try:
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(capacity)):
                return os.path.basename(buffer.value)
            return ""
        finally:
            kernel32.CloseHandle(process)

    def _accessible_elements(self, handle: int) -> tuple[list[dict[str, Any]], str | None]:
        try:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            try:
                try:
                    from comtypes.gen import UIAutomationClient as UIA
                except ImportError:
                    comtypes.client.GetModule("UIAutomationCore.dll")
                    from comtypes.gen import UIAutomationClient as UIA
                automation = comtypes.client.CreateObject(
                    UIA.CUIAutomation, interface=UIA.IUIAutomation,
                )
                root = automation.ElementFromHandle(handle)
                walker = automation.ControlViewWalker
                output: list[dict[str, Any]] = []

                def visit(element: Any, depth: int) -> None:
                    if not element or depth > self.max_depth or len(output) >= self.max_elements:
                        return
                    try:
                        name = str(element.CurrentName or "").strip()
                        automation_id = str(element.CurrentAutomationId or "").strip()
                        class_name = str(element.CurrentClassName or "").strip()
                        control_type = int(element.CurrentControlType)
                        enabled = bool(element.CurrentIsEnabled)
                        rectangle = element.CurrentBoundingRectangle
                        bounds = [int(rectangle.left), int(rectangle.top), int(rectangle.right), int(rectangle.bottom)]
                    except (AttributeError, OSError):
                        return
                    if name or automation_id or class_name:
                        output.append({
                            "name": name[:500], "automation_id": automation_id[:200],
                            "class_name": class_name[:200], "control_type": control_type,
                            "enabled": enabled, "bounds": bounds, "depth": depth,
                        })
                    child = walker.GetFirstChildElement(element)
                    while child and len(output) < self.max_elements:
                        visit(child, depth + 1)
                        child = walker.GetNextSiblingElement(child)

                visit(root, 0)
                return output, None
            finally:
                comtypes.CoUninitialize()
        except Exception as error:
            return [], f"{type(error).__name__}: {error}"

    def find_element(self, handle: int, name: str, *, control_types: tuple[int, ...] = ()) -> Any:
        """Return a live UIA element for an explicit action; caller owns COM scope."""
        import comtypes.client

        try:
            from comtypes.gen import UIAutomationClient as UIA
        except ImportError:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA
        automation = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        root = automation.ElementFromHandle(handle)
        walker = automation.ControlViewWalker
        query = " ".join(name.casefold().split())
        partial: Any = None
        visited = 0

        def walk(element: Any, depth: int) -> Any:
            nonlocal partial, visited
            if not element or depth > self.max_depth or visited >= self.max_elements:
                return None
            visited += 1
            try:
                current_name = " ".join(str(element.CurrentName or "").casefold().split())
                control_type = int(element.CurrentControlType)
                enabled = bool(element.CurrentIsEnabled)
            except (AttributeError, OSError):
                return None
            allowed_type = not control_types or control_type in control_types
            if enabled and allowed_type and current_name == query:
                return element
            if enabled and allowed_type and query and query in current_name and partial is None:
                partial = element
            child = walker.GetFirstChildElement(element)
            while child:
                result = walk(child, depth + 1)
                if result:
                    return result
                child = walker.GetNextSiblingElement(child)
            return None

        return walk(root, 0) or partial

    @staticmethod
    def _visual_fingerprint(bounds: tuple[int, int, int, int]) -> dict[str, Any] | None:
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab(bbox=bounds, all_screens=True)
            sample = image.convert("L").resize((32, 32))
            digest = hashlib.sha256(sample.tobytes()).hexdigest()
            return {"sha256": digest, "width": image.width, "height": image.height, "persisted": False}
        except Exception:
            return None

    @staticmethod
    def _state_hash(evidence: dict[str, Any]) -> str:
        window = evidence["window"]
        parts = [window["title"], window["process_name"], str(window["bounds"])]
        for item in evidence["elements"]:
            parts.extend((item["name"], item["automation_id"], str(item["bounds"])))
        visual = evidence.get("visual")
        if visual:
            parts.append(visual["sha256"])
        return hashlib.sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()


class WindowsDesktopController:
    """Explicit UIA actions with state-based verification and no coordinate fallback."""

    def __init__(self) -> None:
        # Actions need to reach controls inside nested Chromium accessibility
        # trees; observation remains bounded by max_elements.
        self.observer = WindowsDesktopObserver(max_elements=500, max_depth=32)
        self._held_keys: set[str] = set()

    KEY_CODES = {
        "ctrl": 0x11, "shift": 0x10, "alt": 0x12,
        "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "space": 0x20,
        "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
        "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
        "f11": 0x7A, "f12": 0x7B,
        **{chr(code).casefold(): code for code in range(0x41, 0x5B)},
        **{str(number): 0x30 + number for number in range(10)},
    }

    def invoke(self, name: str) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("element_name_required")
        import comtypes
        import comtypes.client

        window = self.observer.active_window()
        before = self.observer.observe_active(include_screenshot_hash=False)["state_hash"]
        comtypes.CoInitialize()
        try:
            try:
                from comtypes.gen import UIAutomationClient as UIA
            except ImportError:
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient as UIA
            element = self.observer.find_element(window.handle, name)
            if not element:
                raise LookupError("ui_element_not_found")
            resolved_name = str(element.CurrentName or name)
            try:
                pattern = element.GetCurrentPattern(UIA.UIA_InvokePatternId)
                pattern.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                method = "invoke_pattern"
            except Exception:
                try:
                    pattern = element.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                    pattern.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
                    method = "selection_item_pattern"
                except Exception as error:
                    raise RuntimeError("ui_element_not_invokable") from error
        finally:
            comtypes.CoUninitialize()
        time.sleep(0.12)
        after_evidence = self.observer.observe_active(include_screenshot_hash=False)
        return {
            "element": resolved_name,
            "method": method,
            "before_hash": before,
            "after_hash": after_evidence["state_hash"],
            "changed_state": before != after_evidence["state_hash"],
            "window": after_evidence["window"],
        }

    def locate(
        self, name: str, *, control_types: tuple[int, ...] = (), expected_window_handle: int = 0,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("element_name_required")
        import comtypes

        window = self.observer.active_window()
        if expected_window_handle and window.handle != expected_window_handle:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if not user32.IsWindow(expected_window_handle):
                raise RuntimeError("target_window_changed")
            self._focus_window(expected_window_handle)
            time.sleep(0.08)
            window = self.observer.active_window()
            if window.handle != expected_window_handle:
                raise RuntimeError("target_window_not_focused")
        comtypes.CoInitialize()
        try:
            element = self.observer.find_element(window.handle, name, control_types=control_types)
            if not element:
                raise LookupError("ui_element_not_found")
            rectangle = element.CurrentBoundingRectangle
            bounds = [int(rectangle.left), int(rectangle.top), int(rectangle.right), int(rectangle.bottom)]
            return {
                "element": str(element.CurrentName or name), "bounds": bounds,
                "enabled": bool(element.CurrentIsEnabled), "control_type": int(element.CurrentControlType),
                "window": window.public(), "changed_state": False,
            }
        finally:
            comtypes.CoUninitialize()

    def manage_window(self, action: str, *, handle: int = 0, bounds: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        target = int(handle or user32.GetForegroundWindow())
        if not target or not user32.IsWindow(target):
            raise ValueError("window_not_found")
        action = action.casefold().strip()
        if action in {"focus", "switch"}:
            before_handle = int(user32.GetForegroundWindow())
            self._focus_window(target)
            time.sleep(0.08)
            changed = before_handle != int(user32.GetForegroundWindow())
            verified = int(user32.GetForegroundWindow()) == target
        elif action == "minimize":
            changed = bool(user32.ShowWindow(target, 6))
            verified = bool(user32.IsIconic(target))
        elif action == "maximize":
            changed = bool(user32.ShowWindow(target, 3))
            verified = bool(user32.IsZoomed(target))
        elif action == "restore":
            changed = bool(user32.ShowWindow(target, 9))
            verified = not bool(user32.IsIconic(target))
        elif action == "move":
            if bounds is None:
                raise ValueError("window_bounds_required")
            x, y, width, height = (int(item) for item in bounds)
            if width < 160 or height < 100 or width > 16384 or height > 16384:
                raise ValueError("invalid_window_bounds")
            changed = bool(user32.SetWindowPos(target, 0, x, y, width, height, 0x0004))
            info = self.observer._window_info(target)
            verified = info.bounds == (x, y, x + width, y + height)
        elif action == "resize":
            if bounds is None:
                raise ValueError("window_bounds_required")
            width, height = int(bounds[2]), int(bounds[3])
            current = self.observer._window_info(target)
            x, y = current.bounds[0], current.bounds[1]
            if width < 160 or height < 100 or width > 16384 or height > 16384:
                raise ValueError("invalid_window_bounds")
            changed = bool(user32.SetWindowPos(target, 0, x, y, width, height, 0x0004))
            info = self.observer._window_info(target)
            verified = info.bounds == (x, y, x + width, y + height)
        else:
            raise ValueError("unsupported_window_action")
        info = self.observer._window_info(target)
        return {
            "action": action, "window": info.public(), "changed_state": changed,
            "verified_state": verified,
        }

    def close_window(self, handle: int, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not handle or not user32.IsWindow(handle):
            raise ValueError("window_not_found")
        before = self.observer._window_info(handle)
        user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE
        closed = self.observer.wait_until_closed(handle, timeout_seconds=timeout_seconds)
        return {
            "action": "close", "window": before.public(), "closed": closed,
            "changed_state": closed,
        }

    def launch_notepad(self, path: str, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError("notepad_target_not_found")
        subprocess.Popen(
            ["notepad.exe", str(target)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + max(1.0, min(timeout_seconds, 20.0))
        selected: WindowInfo | None = None
        while time.monotonic() < deadline:
            candidates = [
                item for item in self.observer.list_windows(limit=200)
                if item.process_name.casefold() == "notepad.exe" and target.name.casefold() in item.title.casefold()
            ]
            if candidates:
                selected = candidates[0]
                break
            time.sleep(0.1)
        if selected is None:
            raise RuntimeError("notepad_window_not_verified")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._focus_window(selected.handle)
        time.sleep(0.1)
        if int(user32.GetForegroundWindow()) != selected.handle:
            raise RuntimeError("notepad_window_not_focused")
        return {"app": "Notepad", "path": str(target), "window": selected.public(), "changed_state": True}

    @staticmethod
    def _focus_window(handle: int) -> None:
        """Focus a verified window across GUI threads without coordinate input."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        foreground = int(user32.GetForegroundWindow())
        current_thread = int(ctypes.WinDLL("kernel32", use_last_error=True).GetCurrentThreadId())
        foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        attached = bool(foreground_thread and foreground_thread != current_thread)
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, True)
        try:
            user32.ShowWindow(handle, 9)
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            user32.SetFocus(handle)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)

    def reveal_in_explorer(self, path: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        """Open Explorer at an explicit item and verify the item is visible there."""
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError("explorer_target_not_found")
        # SHOpenFolderAndSelectItems avoids Explorer's single-process command
        # line reuse selecting an unrelated existing Desktop window.
        if target.is_dir():
            os.startfile(str(target))
        else:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            ole32 = ctypes.OleDLL("ole32")
            pidl = ctypes.c_void_p()
            attributes = wintypes.DWORD()
            shell32.SHParseDisplayName.argtypes = (
                wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            )
            shell32.SHParseDisplayName.restype = ctypes.c_long
            shell32.SHOpenFolderAndSelectItems.argtypes = (
                ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD,
            )
            shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long
            ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
            ole32.CoInitialize(None)
            try:
                parsed = shell32.SHParseDisplayName(
                    str(target), None, ctypes.byref(pidl), 0, ctypes.byref(attributes),
                )
                if parsed != 0 or not pidl.value:
                    raise OSError(f"explorer_parse_failed:{parsed}")
                selected_code = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
                if selected_code != 0:
                    raise OSError(f"explorer_select_failed:{selected_code}")
            finally:
                if pidl.value:
                    ole32.CoTaskMemFree(pidl)
                ole32.CoUninitialize()
        deadline = time.monotonic() + max(1.0, min(timeout_seconds, 30.0))
        selected: WindowInfo | None = None
        visible = False
        while time.monotonic() < deadline:
            candidates = [
                item for item in self.observer.find_windows(process_name="explorer.exe", limit=100)
                if item.class_name == "CabinetWClass"
            ]
            for candidate in candidates:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.ShowWindow(candidate.handle, 9)
                self._focus_window(candidate.handle)
                time.sleep(0.08)
                selected = self.observer._window_info(candidate.handle)
                if target.is_dir():
                    visible = True
                else:
                    try:
                        visible = self.observer.find_element(candidate.handle, target.name) is not None
                    except (LookupError, OSError, RuntimeError):
                        visible = False
                if visible:
                    break
            if visible:
                break
            time.sleep(0.12)
        if selected is None or not visible:
            raise RuntimeError("explorer_item_not_verified")
        return {
            "app": "Explorer", "path": str(target), "window": selected.public(),
            "item_visible": visible, "changed_state": True,
        }

    def hotkey(self, keys: tuple[str, ...], *, expected_window_handle: int = 0) -> dict[str, Any]:
        normalized = tuple(item.casefold().strip() for item in keys)
        if not normalized or len(normalized) > 4 or any(key not in self.KEY_CODES for key in normalized):
            raise ValueError("invalid_hotkey")
        if len(normalized) > 1 and not any(key in {"ctrl", "alt", "shift"} for key in normalized[:-1]):
            raise ValueError("hotkey_requires_modifier")
        window = self.observer.active_window()
        if expected_window_handle and window.handle != expected_window_handle:
            raise RuntimeError("target_window_changed")
        if not self._focused_element_verified(window.handle):
            raise RuntimeError("focused_control_not_verified")
        for key in normalized:
            self._key_event(key, down=True)
            time.sleep(0.02)
        for key in reversed(normalized):
            self._key_event(key, down=False)
            time.sleep(0.02)
        time.sleep(0.2)
        return {
            "keys": list(normalized), "window": window.public(), "target_verified": True,
            "focused_control_verified": True, "changed_state": True,
        }

    def select_all(self, *, expected_window_handle: int = 0) -> dict[str, Any]:
        """Select an editable document through UIA, independent of localized shortcuts."""
        import comtypes
        import comtypes.client

        window = self.observer.active_window()
        if expected_window_handle and window.handle != expected_window_handle:
            raise RuntimeError("target_window_changed")
        comtypes.CoInitialize()
        try:
            element = self._focused_element(window.handle)
            if not element or not bool(element.CurrentHasKeyboardFocus):
                raise RuntimeError("focused_control_not_verified")
            try:
                from comtypes.gen import UIAutomationClient as UIA
            except ImportError:
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient as UIA
            try:
                pattern = element.GetCurrentPattern(UIA.UIA_TextPatternId).QueryInterface(
                    UIA.IUIAutomationTextPattern,
                )
                document = pattern.DocumentRange
                document.Select()
                selected = pattern.GetSelection()
                verified = bool(selected and selected.Length > 0)
                method = "uia_text_pattern"
            except Exception as error:
                raise RuntimeError("select_all_not_supported") from error
        finally:
            comtypes.CoUninitialize()
        return {
            "action": "select_all", "method": method, "window": window.public(),
            "target_verified": True, "focused_control_verified": True,
            "selection_verified": verified, "changed_state": False,
        }

    def key_action(self, action: str, key: str, *, expected_window_handle: int = 0) -> dict[str, Any]:
        action = action.casefold().strip()
        key = key.casefold().strip()
        if key not in self.KEY_CODES:
            raise ValueError("unsupported_key")
        window = self.observer.active_window()
        if expected_window_handle and window.handle != expected_window_handle:
            raise RuntimeError("target_window_changed")
        if not self._focused_element_verified(window.handle):
            raise RuntimeError("focused_control_not_verified")
        if action == "press":
            self._key_event(key, down=True)
            self._key_event(key, down=False)
        elif action == "down":
            self._key_event(key, down=True)
            self._held_keys.add(key)
        elif action == "up":
            self._key_event(key, down=False)
            self._held_keys.discard(key)
        else:
            raise ValueError("unsupported_key_action")
        return {
            "action": action, "key": key, "window": window.public(),
            "target_verified": True, "focused_control_verified": True,
            "held_keys": sorted(self._held_keys), "changed_state": True,
        }

    def release_all_keys(self) -> None:
        for key in tuple(self._held_keys):
            self._key_event(key, down=False)
        self._held_keys.clear()

    def _key_event(self, key: str, *, down: bool) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.keybd_event(self.KEY_CODES[key], 0, 0 if down else 0x0002, 0)

    def _focused_element_verified(self, handle: int) -> bool:
        import comtypes

        comtypes.CoInitialize()
        try:
            element = self._focused_element(handle)
            return bool(element and element.CurrentHasKeyboardFocus)
        finally:
            comtypes.CoUninitialize()

    def type_text(
        self, text: str, *, field_name: str = "", expected_window_handle: int = 0,
    ) -> dict[str, Any]:
        if not text:
            raise ValueError("text_required")
        import comtypes
        import comtypes.client

        window = self.observer.active_window()
        if expected_window_handle and window.handle != expected_window_handle:
            raise RuntimeError("target_window_changed")
        comtypes.CoInitialize()
        try:
            element = self.observer.find_element(
                window.handle,
                field_name,
                control_types=(50004, 50030),  # Edit, Document
            ) if field_name else self._focused_element(window.handle)
            if not element:
                raise LookupError("editable_control_not_found")
            if field_name:
                element.SetFocus()
                time.sleep(0.05)
            if not bool(element.CurrentHasKeyboardFocus):
                raise RuntimeError("editable_control_not_focused")
            focused_name = str(element.CurrentName or field_name or "editable control")
            try:
                from comtypes.gen import UIAutomationClient as UIA
            except ImportError:
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient as UIA
            method = "send_input"
            input_verified = False
            verification_method = "uia_readback"
            try:
                value = element.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(
                    UIA.IUIAutomationValuePattern,
                )
                if bool(value.CurrentIsReadOnly):
                    raise RuntimeError("editable_control_is_read_only")
                # Modern Notepad exposes a native handle that is not a classic
                # Win32 EDIT control. UIA ValuePattern is the semantic path for
                # both modern and classic editors and can be read back exactly.
                value.SetValue(text)
                method = "uia_value_pattern"
                input_verified = self._element_text(element, UIA) == text
            except Exception:
                self._send_unicode(text)
                observed_text = self._element_text(element, UIA)
                input_verified = observed_text == text or observed_text.endswith(text)
            if not input_verified:
                input_verified = self._verify_focused_text_via_clipboard(text)
                verification_method = "temporary_clipboard_readback"
        finally:
            comtypes.CoUninitialize()
        time.sleep(0.08)
        return {
            "focused_control": focused_name,
            "characters_typed": len(text),
            "method": method,
            "input_verified": input_verified,
            "verification_method": verification_method,
            "target_verified": True,
            "focused_control_verified": True,
            "changed_state": True,
        }

    def _verify_focused_text_via_clipboard(self, expected: str) -> bool:
        """Read back otherwise opaque web text without retaining clipboard data."""
        from .clipboard import WindowsClipboard

        clipboard = WindowsClipboard()
        previous = clipboard.read_text()
        try:
            for key in ("ctrl", "a"):
                self._key_event(key, down=True)
            for key in ("a", "ctrl"):
                self._key_event(key, down=False)
            time.sleep(0.04)
            for key in ("ctrl", "c"):
                self._key_event(key, down=True)
            for key in ("c", "ctrl"):
                self._key_event(key, down=False)
            time.sleep(0.08)
            return clipboard.read_text().replace("\r\n", "\n") == expected.replace("\r\n", "\n")
        finally:
            clipboard.write_text(previous)

    @staticmethod
    def _element_text(element: Any, UIA: Any) -> str:
        try:
            value = element.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(
                UIA.IUIAutomationValuePattern,
            )
            return str(value.CurrentValue).replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            try:
                pattern = element.GetCurrentPattern(UIA.UIA_TextPatternId).QueryInterface(
                    UIA.IUIAutomationTextPattern,
                )
                return str(pattern.DocumentRange.GetText(-1)).replace("\r\n", "\n").rstrip("\r\n")
            except Exception:
                return ""

    @staticmethod
    def _focused_element(handle: int) -> Any:
        import comtypes.client

        try:
            from comtypes.gen import UIAutomationClient as UIA
        except ImportError:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA
        automation = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        focused = automation.GetFocusedElement()
        if not focused:
            return None
        native_handle = int(getattr(focused, "CurrentNativeWindowHandle", 0) or 0)
        if native_handle and native_handle != handle:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if not user32.IsChild(handle, native_handle):
                return None
        return focused

    @staticmethod
    def _send_unicode(text: str) -> None:
        ULONG_PTR = wintypes.WPARAM

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = (
                ("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
            )

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = (
                ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            )

        class INPUT_UNION(ctypes.Union):
            _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))

        class INPUT(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = (("type", wintypes.DWORD), ("value", INPUT_UNION))

        units = text.encode("utf-16-le")
        inputs: list[INPUT] = []
        for index in range(0, len(units), 2):
            scan = int.from_bytes(units[index:index + 2], "little")
            inputs.append(INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, scan, 0x0004, 0, 0))))
            inputs.append(INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, scan, 0x0006, 0, 0))))
        array_type = INPUT * len(inputs)
        sent = ctypes.windll.user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise ctypes.WinError(ctypes.get_last_error())
