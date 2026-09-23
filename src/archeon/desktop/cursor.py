"""Transient, click-through ARCHI cursor feedback for physical mouse actions."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any


CURSOR_STATES = frozenset({
    "moving", "targeting", "click", "double_click", "drag", "scroll", "waiting", "error",
})


class ArchiCursorOverlay:
    """Draws a short-lived native marker only while ARCHI is acting."""

    def __init__(self) -> None:
        self._threads: set[threading.Thread] = set()
        self._lock = threading.RLock()

    def show(
        self,
        point: tuple[int, int],
        *,
        state: str = "targeting",
        duration_ms: int = 420,
        accent_bgr: int = 0xFFFF00,
        reduce_motion: bool = False,
    ) -> dict[str, Any]:
        state = state.casefold().strip()
        if state not in CURSOR_STATES:
            raise ValueError("invalid_cursor_state")
        duration_ms = max(140, min(int(duration_ms), 2_500))
        if reduce_motion:
            duration_ms = min(duration_ms, 260)
        ready = threading.Event()
        result: dict[str, Any] = {}
        thread = threading.Thread(
            target=self._run,
            args=(tuple(map(int, point)), state, duration_ms, int(accent_bgr), ready, result),
            name="archeon-cursor-overlay",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()
        if not ready.wait(1.0):
            raise TimeoutError("cursor_overlay_start_timeout")
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return {
            "shown": bool(result.get("handle")),
            "handle": int(result.get("handle", 0)),
            "point": [int(point[0]), int(point[1])],
            "state": state,
            "duration_ms": duration_ms,
            "click_through": True,
            "steals_focus": False,
            "resident": False,
        }

    def _run(
        self,
        point: tuple[int, int],
        state: str,
        duration_ms: int,
        accent_bgr: int,
        ready: threading.Event,
        result: dict[str, Any],
    ) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        thread = threading.current_thread()
        try:
            if hasattr(user32, "SetThreadDpiAwarenessContext"):
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            user32.CreateWindowExW.argtypes = (
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
            )
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = (
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            )
            user32.SetLayeredWindowAttributes.argtypes = (
                wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD,
            )
            user32.BeginPaint.restype = wintypes.HDC
            user32.DefWindowProcW.argtypes = (
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            )
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            gdi32.CreatePen.restype = wintypes.HANDLE
            gdi32.GetStockObject.restype = wintypes.HANDLE
            gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
            gdi32.SelectObject.restype = wintypes.HANDLE
            gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
            gdi32.Ellipse.argtypes = (
                wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            )
            gdi32.MoveToEx.argtypes = (
                wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.POINT),
            )
            gdi32.LineTo.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
            WM_PAINT, WM_TIMER, WM_DESTROY = 0x000F, 0x0113, 0x0002
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = (
                    ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                )

            class PAINTSTRUCT(ctypes.Structure):
                _fields_ = (
                    ("hdc", wintypes.HDC), ("fErase", wintypes.BOOL),
                    ("rcPaint", wintypes.RECT), ("fRestore", wintypes.BOOL),
                    ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32),
                )

            @WNDPROC
            def window_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
                if message == WM_PAINT:
                    paint = PAINTSTRUCT()
                    dc = user32.BeginPaint(hwnd, ctypes.byref(paint))
                    pen = gdi32.CreatePen(0, 3, accent_bgr)
                    old_pen = gdi32.SelectObject(dc, pen)
                    old_brush = gdi32.SelectObject(dc, gdi32.GetStockObject(5))
                    gdi32.Ellipse(dc, 5, 5, 43, 43)
                    gdi32.MoveToEx(dc, 24, 0, None)
                    gdi32.LineTo(dc, 24, 12)
                    gdi32.MoveToEx(dc, 24, 36, None)
                    gdi32.LineTo(dc, 24, 48)
                    gdi32.MoveToEx(dc, 0, 24, None)
                    gdi32.LineTo(dc, 12, 24)
                    gdi32.MoveToEx(dc, 36, 24, None)
                    gdi32.LineTo(dc, 48, 24)
                    gdi32.SelectObject(dc, old_brush)
                    gdi32.SelectObject(dc, old_pen)
                    gdi32.DeleteObject(pen)
                    user32.EndPaint(hwnd, ctypes.byref(paint))
                    return 0
                if message == WM_TIMER:
                    user32.DestroyWindow(hwnd)
                    return 0
                if message == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            instance = kernel32.GetModuleHandleW(None)
            class_name = f"ARCHEONCursorOverlay{threading.get_ident()}"
            window_class = WNDCLASSW(
                0, window_proc, 0, 0, instance, None, None,
                gdi32.CreateSolidBrush(0), None, class_name,
            )
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            width, height = 48, 48
            ex_style = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
            hwnd = user32.CreateWindowExW(
                ex_style, class_name, "", 0x80000000,
                point[0] - 24, point[1] - 24, width, height,
                None, None, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000001)
            user32.SetWindowPos(
                hwnd, -1, point[0] - 24, point[1] - 24, width, height,
                0x0010 | 0x0040,
            )
            user32.SetTimer(hwnd, 1, duration_ms, None)
            result["handle"] = int(hwnd)
            ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            user32.UnregisterClassW(class_name, instance)
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
            ready.set()
        finally:
            with self._lock:
                self._threads.discard(thread)
