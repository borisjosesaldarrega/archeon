"""Permission-gated desktop tools registered lazily in the shared ToolEngine."""

from __future__ import annotations

import time
from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .clipboard import WindowsClipboard
from .mouse import WindowsMouseFallback
from .overlay import GuideOverlay
from .windows import WindowsDesktopController, WindowsDesktopObserver


OBSERVE_ACTIVE_MANIFEST = ToolManifest(
    id="desktop.observe_active",
    description="Inspect the active window locally using Windows UI Automation",
    permissions=("desktop.observe",),
    risk=RiskLevel.READ_ONLY,
    timeout_seconds=10.0,
    resource_class="on_demand",
)

INVOKE_MANIFEST = ToolManifest(
    id="desktop.invoke",
    description="Invoke a named control in the active application through Windows UI Automation",
    permissions=("desktop.control",),
    risk=RiskLevel.LOW,
    timeout_seconds=10.0,
    resource_class="on_demand",
)

TYPE_TEXT_MANIFEST = ToolManifest(
    id="desktop.type_text",
    description="Type into a verified focused editable control",
    permissions=("desktop.control",),
    risk=RiskLevel.LOW,
    timeout_seconds=10.0,
    resource_class="on_demand",
)

LOCATE_MANIFEST = ToolManifest(
    id="desktop.locate",
    description="Locate a named control for GUIDE mode without interacting",
    permissions=("desktop.observe",),
    risk=RiskLevel.READ_ONLY,
    timeout_seconds=10.0,
    resource_class="on_demand",
)

LIST_WINDOWS_MANIFEST = ToolManifest(
    id="desktop.list_windows", description="List visible top-level Windows windows",
    permissions=("desktop.observe",), risk=RiskLevel.READ_ONLY, timeout_seconds=10.0,
)

WINDOW_ACTION_MANIFEST = ToolManifest(
    id="desktop.window_action", description="Focus, switch, minimize, maximize, restore, move or resize one window",
    permissions=("desktop.control",), risk=RiskLevel.LOW, timeout_seconds=10.0,
)

FIND_WINDOW_MANIFEST = ToolManifest(
    id="desktop.find_window", description="Find or wait for a visible window by title or process",
    permissions=("desktop.observe",), risk=RiskLevel.READ_ONLY, timeout_seconds=120.0,
)

CLOSE_WINDOW_MANIFEST = ToolManifest(
    id="desktop.close_window", description="Request one explicit window to close and verify it closed",
    permissions=("desktop.close",), risk=RiskLevel.MEDIUM, timeout_seconds=120.0,
)

LAUNCH_NOTEPAD_MANIFEST = ToolManifest(
    id="desktop.launch_notepad", description="Open one verified local file in Windows Notepad",
    permissions=("desktop.control", "filesystem.read"), risk=RiskLevel.LOW, timeout_seconds=20.0,
)

REVEAL_EXPLORER_MANIFEST = ToolManifest(
    id="desktop.reveal_in_explorer", description="Open Explorer and reveal one verified local item",
    permissions=("desktop.control", "filesystem.read"), risk=RiskLevel.LOW, timeout_seconds=30.0,
)

HOTKEY_MANIFEST = ToolManifest(
    id="desktop.hotkey", description="Send one allowlisted hotkey to a verified focused control",
    permissions=("desktop.control",), risk=RiskLevel.LOW, timeout_seconds=5.0,
)

KEYBOARD_MANIFEST = ToolManifest(
    id="desktop.keyboard", description="Send a verified keyboard action to the focused control",
    permissions=("desktop.control",), risk=RiskLevel.LOW, timeout_seconds=5.0,
)

CLIPBOARD_READ_MANIFEST = ToolManifest(
    id="desktop.clipboard_read", description="Read current text from the Windows clipboard without logging it",
    permissions=("clipboard.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=5.0,
)

CLIPBOARD_WRITE_MANIFEST = ToolManifest(
    id="desktop.clipboard_write", description="Write or clear temporary Windows clipboard text",
    permissions=("clipboard.write",), risk=RiskLevel.LOW, timeout_seconds=5.0,
)

GUIDE_OVERLAY_MANIFEST = ToolManifest(
    id="desktop.guide_overlay", description="Show a temporary click-through highlight over a verified control",
    permissions=("desktop.observe",), risk=RiskLevel.READ_ONLY, timeout_seconds=5.0,
)

MOUSE_FALLBACK_MANIFEST = ToolManifest(
    id="desktop.mouse_fallback",
    description="Use DPI-aware physical mouse input only after structured interaction is unavailable",
    permissions=("desktop.control",), risk=RiskLevel.LOW, timeout_seconds=5.0,
)


class ObserveActiveWindowTool:
    manifest = OBSERVE_ACTIVE_MANIFEST

    def __init__(self) -> None:
        self._observer = WindowsDesktopObserver()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        evidence = self._observer.observe_active(
            include_screenshot_hash=bool(arguments.get("visual_fingerprint", True)),
        )
        return ToolResult(True, evidence, evidence={"state_hash": evidence["state_hash"]})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        window = result.data.get("window", {})
        return bool(window.get("handle") and window.get("process_id") and result.data.get("state_hash"))


class InvokeNamedControlTool:
    manifest = INVOKE_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._controller.invoke(str(arguments.get("name", "")))
        return ToolResult(
            True, data, evidence={"before_hash": data["before_hash"], "after_hash": data["after_hash"]},
            changed_state=bool(data["changed_state"]),
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.data.get("method") and result.data.get("changed_state"))


class TypeTextTool:
    manifest = TYPE_TEXT_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._controller.type_text(
            str(arguments.get("text", "")), field_name=str(arguments.get("field_name", "")),
            expected_window_handle=int(arguments.get("expected_window_handle", 0)),
        )
        return ToolResult(True, data, evidence={"characters_typed": data["characters_typed"]}, changed_state=True)

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(
            result.data.get("changed_state") and result.data.get("characters_typed", 0) > 0
            and result.data.get("input_verified")
        )


class LocateNamedControlTool:
    manifest = LOCATE_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        names = arguments.get("names")
        candidates = [str(item) for item in names] if isinstance(names, (list, tuple)) else [str(arguments.get("name", ""))]
        raw_types = arguments.get("control_types", ())
        control_types = tuple(int(item) for item in raw_types) if isinstance(raw_types, (list, tuple)) else ()
        expected_window_handle = int(arguments.get("expected_window_handle", 0))
        data = None
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                data = self._controller.locate(
                    candidate, control_types=control_types,
                    expected_window_handle=expected_window_handle,
                )
                break
            except LookupError as error:
                last_error = error
        if data is None:
            raise last_error or LookupError("ui_element_not_found")
        return ToolResult(True, data, evidence={"bounds": data["bounds"], "element": data["element"]})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        bounds = result.data.get("bounds", [])
        return bool(result.data.get("enabled") and len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1])


class ListWindowsTool:
    manifest = LIST_WINDOWS_MANIFEST

    def __init__(self) -> None:
        self._observer = WindowsDesktopObserver()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        windows = []
        for item in self._observer.list_windows(limit=int(arguments.get("limit", 100))):
            value = item.public()
            value["application"] = self._observer.classify_window(item)
            windows.append(value)
        return ToolResult(True, {"windows": windows}, evidence={"window_count": len(windows)})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return isinstance(result.data.get("windows"), list)


class WindowActionTool:
    manifest = WINDOW_ACTION_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        raw_bounds = arguments.get("bounds")
        bounds = tuple(int(item) for item in raw_bounds) if isinstance(raw_bounds, (list, tuple)) and len(raw_bounds) == 4 else None
        data = self._controller.manage_window(
            str(arguments.get("action", "")), handle=int(arguments.get("handle", 0)), bounds=bounds,
        )
        return ToolResult(
            True, data, evidence={"verified_state": data["verified_state"]},
            changed_state=bool(data["changed_state"]),
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.data.get("verified_state"))


class FindWindowTool:
    manifest = FIND_WINDOW_MANIFEST

    def __init__(self) -> None:
        self._observer = WindowsDesktopObserver()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        wait = bool(arguments.get("wait", False))
        title = str(arguments.get("title", ""))
        process_name = str(arguments.get("process_name", ""))
        if wait:
            deadline = time.monotonic() + max(0.1, min(float(arguments.get("timeout_seconds", 10.0)), 120.0))
            window = None
            while time.monotonic() < deadline:
                if context.cancel_event is not None and context.cancel_event.is_set():
                    return ToolResult(False, {"windows": []}, error="cancelled", error_code="cancelled")
                matches = self._observer.find_windows(title=title, process_name=process_name, limit=1)
                if matches:
                    window = matches[0]
                    break
                time.sleep(0.08)
            if window is None:
                raise TimeoutError("window_wait_timeout")
            windows = [window.public()]
        elif arguments.get("wait_until_closed"):
            handle = int(arguments.get("handle", 0))
            closed = self._observer.wait_until_closed(
                handle, timeout_seconds=float(arguments.get("timeout_seconds", 10.0)),
            )
            return ToolResult(
                closed, {"handle": handle, "closed": closed},
                error=None if closed else "window_close_timeout",
                error_code=None if closed else "timeout", evidence={"closed": closed},
            )
        else:
            windows = [item.public() for item in self._observer.find_windows(
                title=title, process_name=process_name, exact=bool(arguments.get("exact", False)),
                limit=int(arguments.get("limit", 20)),
            )]
        return ToolResult(True, {"windows": windows}, evidence={"matches": len(windows)})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("closed") or result.evidence.get("matches", 0) > 0)


class CloseWindowTool:
    manifest = CLOSE_WINDOW_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._controller.close_window(
            int(arguments.get("handle", 0)),
            timeout_seconds=float(arguments.get("timeout_seconds", 10.0)),
        )
        return ToolResult(
            bool(data["closed"]), data,
            error=None if data["closed"] else "window_not_closed",
            error_code=None if data["closed"] else "verification_failed",
            evidence={"closed": data["closed"]}, changed_state=bool(data["closed"]),
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("closed"))


class LaunchNotepadTool:
    manifest = LAUNCH_NOTEPAD_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._controller.launch_notepad(
            str(arguments.get("path", "")), timeout_seconds=float(arguments.get("timeout_seconds", 8.0)),
        )
        return ToolResult(
            True, data, evidence={"window_handle": data["window"]["handle"], "process": data["window"]["process_name"]},
            changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("window_handle") and result.evidence.get("process") == "Notepad.exe")


class RevealInExplorerTool:
    manifest = REVEAL_EXPLORER_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._controller.reveal_in_explorer(
            str(arguments.get("path", "")), timeout_seconds=float(arguments.get("timeout_seconds", 10.0)),
        )
        return ToolResult(
            True, data,
            evidence={"window_handle": data["window"]["handle"], "item_visible": data["item_visible"]},
            changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("window_handle") and result.evidence.get("item_visible"))


class HotkeyTool:
    manifest = HOTKEY_MANIFEST

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        keys = tuple(str(item) for item in arguments.get("keys", ()))
        data = self._controller.hotkey(
            keys, expected_window_handle=int(arguments.get("expected_window_handle", 0)),
        )
        return ToolResult(True, data, evidence={"keys_sent": len(keys)}, changed_state=True)

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("keys_sent"))


class KeyboardTool:
    manifest = KEYBOARD_MANIFEST
    _SHORTCUTS = {
        "copy": ("ctrl", "c"), "paste": ("ctrl", "v"),
        "escape": ("escape",), "enter": ("enter",), "tab": ("tab",),
    }

    def __init__(self) -> None:
        self._controller = WindowsDesktopController()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "")).casefold()
        expected_handle = int(arguments.get("expected_window_handle", 0))
        if action == "hotkey":
            data = self._controller.hotkey(
                tuple(str(item) for item in arguments.get("keys", ())),
                expected_window_handle=expected_handle,
            )
        elif action == "select_all":
            data = self._controller.select_all(expected_window_handle=expected_handle)
        elif action in self._SHORTCUTS:
            data = self._controller.hotkey(
                self._SHORTCUTS[action], expected_window_handle=expected_handle,
            )
        elif action in {"press_key", "key_down", "key_up"}:
            data = self._controller.key_action(
                {"press_key": "press", "key_down": "down", "key_up": "up"}[action],
                str(arguments.get("key", "")),
                expected_window_handle=int(arguments.get("expected_window_handle", 0)),
            )
        else:
            raise ValueError("unsupported_keyboard_action")
        return ToolResult(
            True, data, evidence={
                "target_verified": data.get("target_verified", False),
                "focused_control_verified": data.get("focused_control_verified", False),
            }, changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("target_verified") and result.evidence.get("focused_control_verified"))

    def close(self) -> None:
        self._controller.release_all_keys()


class ClipboardReadTool:
    manifest = CLIPBOARD_READ_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        text = WindowsClipboard().read_text()
        return ToolResult(
            True, {"clipboard_text": text, "characters": len(text)},
            evidence={"read_succeeded": True, "characters": len(text)},
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("read_succeeded"))


class ClipboardWriteTool:
    manifest = CLIPBOARD_WRITE_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        clipboard = WindowsClipboard()
        action = str(arguments.get("action", "write")).casefold()
        if action == "clear":
            clipboard.clear()
            expected = ""
        elif action == "write":
            expected = str(arguments.get("text", ""))
            clipboard.write_text(expected)
        else:
            raise ValueError("unsupported_clipboard_action")
        verified = clipboard.read_text() == expected
        return ToolResult(
            verified, {"action": action, "characters": len(expected)},
            error=None if verified else "clipboard_verification_failed",
            error_code=None if verified else "verification_failed",
            evidence={"exact_match": verified}, changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("exact_match"))


class GuideOverlayTool:
    manifest = GUIDE_OVERLAY_MANIFEST

    def __init__(self) -> None:
        self._observer = WindowsDesktopObserver()
        self._overlay = GuideOverlay()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        bounds = tuple(int(value) for value in arguments.get("bounds", ()))
        if len(bounds) != 4:
            raise ValueError("invalid_overlay_bounds")
        expected_handle = int(arguments.get("window_handle", 0))
        active = self._observer.active_window()
        if expected_handle and active.handle != expected_handle:
            raise RuntimeError("target_window_changed")
        if bounds[0] < active.bounds[0] - 100 or bounds[1] < active.bounds[1] - 100:
            raise RuntimeError("target_rectangle_stale")
        data = self._overlay.show(
            bounds, label=str(arguments.get("label", "")),
            duration_ms=int(arguments.get("duration_ms", 1800)),
        )
        data["target_window"] = active.public()
        return ToolResult(
            bool(data["shown"]), data,
            error=None if data["shown"] else "overlay_not_shown",
            error_code=None if data["shown"] else "verification_failed",
            evidence={"overlay_handle": data["handle"], "click_through": data["click_through"]},
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("overlay_handle") and result.evidence.get("click_through"))


class MouseFallbackTool:
    manifest = MOUSE_FALLBACK_MANIFEST

    def __init__(self) -> None:
        self._mouse = WindowsMouseFallback()

    def close(self) -> None:
        self._mouse.release_all()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        def rectangle(name: str) -> tuple[int, int, int, int]:
            value = arguments.get(name, ())
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError(f"invalid_{name}")
            return tuple(int(item) for item in value)

        raw_destination = arguments.get("destination")
        destination = None
        if raw_destination is not None:
            if not isinstance(raw_destination, (list, tuple)) or len(raw_destination) != 2:
                raise ValueError("invalid_destination")
            destination = (int(raw_destination[0]), int(raw_destination[1]))
        before_hash = self._mouse.observer.observe_active(include_screenshot_hash=False)["state_hash"]
        data = self._mouse.perform(
            str(arguments.get("action", "")),
            window_handle=int(arguments.get("window_handle", 0)),
            observed_window_bounds=rectangle("observed_window_bounds"),
            target_bounds=rectangle("target_bounds"), destination=destination,
            scroll_delta=int(arguments.get("scroll_delta", 0)),
            button=str(arguments.get("button", "left")),
            show_cursor=bool(arguments.get("show_cursor", True)),
            reduce_motion=bool(arguments.get("reduce_motion", False)),
            accent_bgr=int(arguments.get("accent_bgr", 0xFFFF00)),
            movement_mode=str(arguments.get("movement_mode", "normal")),
        )
        time.sleep(0.12)
        after_hash = self._mouse.observer.observe_active(include_screenshot_hash=False)["state_hash"]
        state_changed = before_hash != after_hash
        if data["action"] != "move":
            data["changed_state"] = state_changed
        data["before_hash"] = before_hash
        data["after_hash"] = after_hash
        return ToolResult(
            True, data, evidence={
                "target_revalidated": data["target_revalidated"],
                "before_hash": before_hash, "after_hash": after_hash,
                "state_changed": state_changed,
                "cursor_position_verified": data["cursor_position_verified"],
                "input_dispatched": data["input_dispatched"],
            },
            changed_state=bool(data["changed_state"]),
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        if not result.evidence.get("target_revalidated"):
            return False
        return bool(
            result.evidence.get("cursor_position_verified")
            and result.evidence.get("input_dispatched")
        )


class DesktopAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("desktop_agent")
        self._tools = tools

    def _start(self) -> None:
        self._tools.register(OBSERVE_ACTIVE_MANIFEST, ObserveActiveWindowTool)
        self._tools.register(INVOKE_MANIFEST, InvokeNamedControlTool)
        self._tools.register(TYPE_TEXT_MANIFEST, TypeTextTool)
        self._tools.register(LOCATE_MANIFEST, LocateNamedControlTool)
        self._tools.register(LIST_WINDOWS_MANIFEST, ListWindowsTool)
        self._tools.register(WINDOW_ACTION_MANIFEST, WindowActionTool)
        self._tools.register(FIND_WINDOW_MANIFEST, FindWindowTool)
        self._tools.register(CLOSE_WINDOW_MANIFEST, CloseWindowTool)
        self._tools.register(LAUNCH_NOTEPAD_MANIFEST, LaunchNotepadTool)
        self._tools.register(REVEAL_EXPLORER_MANIFEST, RevealInExplorerTool)
        self._tools.register(HOTKEY_MANIFEST, HotkeyTool)
        self._tools.register(KEYBOARD_MANIFEST, KeyboardTool)
        self._tools.register(CLIPBOARD_READ_MANIFEST, ClipboardReadTool)
        self._tools.register(CLIPBOARD_WRITE_MANIFEST, ClipboardWriteTool)
        self._tools.register(GUIDE_OVERLAY_MANIFEST, GuideOverlayTool)
        self._tools.register(MOUSE_FALLBACK_MANIFEST, MouseFallbackTool)

    def _stop(self) -> None:
        self._tools.unregister(MOUSE_FALLBACK_MANIFEST.id)
        self._tools.unregister(GUIDE_OVERLAY_MANIFEST.id)
        self._tools.unregister(CLOSE_WINDOW_MANIFEST.id)
        self._tools.unregister(FIND_WINDOW_MANIFEST.id)
        self._tools.unregister(CLIPBOARD_WRITE_MANIFEST.id)
        self._tools.unregister(CLIPBOARD_READ_MANIFEST.id)
        self._tools.unregister(KEYBOARD_MANIFEST.id)
        self._tools.unregister(HOTKEY_MANIFEST.id)
        self._tools.unregister(REVEAL_EXPLORER_MANIFEST.id)
        self._tools.unregister(LAUNCH_NOTEPAD_MANIFEST.id)
        self._tools.unregister(WINDOW_ACTION_MANIFEST.id)
        self._tools.unregister(LIST_WINDOWS_MANIFEST.id)
        self._tools.unregister(LOCATE_MANIFEST.id)
        self._tools.unregister(TYPE_TEXT_MANIFEST.id)
        self._tools.unregister(INVOKE_MANIFEST.id)
        self._tools.unregister(OBSERVE_ACTIVE_MANIFEST.id)
