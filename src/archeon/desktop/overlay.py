"""Short-lived native GUIDE overlay; no Tk, WebView or resident process."""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Any


class GuideOverlay:
    def __init__(self) -> None:
        self._threads: set[threading.Thread] = set()
        self._lock = threading.RLock()

    def show(
        self, bounds: tuple[int, int, int, int], *, label: str = "", duration_ms: int = 1800,
    ) -> dict[str, Any]:
        left, top, right, bottom = (int(value) for value in bounds)
        if right <= left or bottom <= top:
            raise ValueError("invalid_overlay_bounds")
        duration_ms = max(500, min(int(duration_ms), 10_000))
        ready = threading.Event()
        result: dict[str, Any] = {}
        thread = threading.Thread(
            target=self._run,
            args=((left, top, right, bottom), label[:80], duration_ms, ready, result),
            name="archeon-guide-overlay", daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()
        if not ready.wait(1.5):
            raise TimeoutError("overlay_start_timeout")
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return {
            "shown": bool(result.get("handle")), "handle": int(result.get("handle", 0)),
            "bounds": [left, top, right, bottom], "label": label[:80],
            "duration_ms": duration_ms, "click_through": True, "steals_focus": False,
        }

    def _run(
        self, bounds: tuple[int, int, int, int], label: str, duration_ms: int,
        ready: threading.Event, result: dict[str, Any],
    ) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
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
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetLayeredWindowAttributes.argtypes = (
                wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD,
            )
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            user32.BeginPaint.restype = wintypes.HDC
            user32.DefWindowProcW.argtypes = (
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            )
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            gdi32.CreatePen.restype = wintypes.HANDLE
            gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
            gdi32.GetStockObject.restype = wintypes.HANDLE
            gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
            gdi32.SelectObject.restype = wintypes.HANDLE
            gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
            gdi32.Rectangle.argtypes = (
                wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            )
            gdi32.SetTextColor.argtypes = (wintypes.HDC, wintypes.DWORD)
            gdi32.SetBkMode.argtypes = (wintypes.HDC, ctypes.c_int)
            gdi32.TextOutW.argtypes = (
                wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int,
            )
            if hasattr(user32, "SetThreadDpiAwarenessContext"):
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
            WM_PAINT, WM_TIMER, WM_DESTROY = 0x000F, 0x0113, 0x0002
            WNDPROC = ctypes.WINFUNCTYPE(
                wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
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
                    device = user32.BeginPaint(hwnd, ctypes.byref(paint))
                    rect = wintypes.RECT()
                    user32.GetClientRect(hwnd, ctypes.byref(rect))
                    pen = gdi32.CreatePen(0, 4, 0xFFFF00)  # cyan in COLORREF BGR order
                    old_pen = gdi32.SelectObject(device, pen)
                    old_brush = gdi32.SelectObject(device, gdi32.GetStockObject(5))  # NULL_BRUSH
                    target_width = bounds[2] - bounds[0]
                    target_height = bounds[3] - bounds[1]
                    gdi32.Rectangle(device, 7, 7, 7 + target_width, 7 + target_height)
                    gdi32.SetTextColor(device, 0xFFFF00)
                    gdi32.SetBkMode(device, 1)
                    if label:
                        gdi32.TextOutW(device, 10, 11 + target_height, label, len(label))
                    gdi32.SelectObject(device, old_brush)
                    gdi32.SelectObject(device, old_pen)
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
            class_name = f"ARCHEONGuideOverlay{threading.get_ident()}"
            window_class = WNDCLASSW(
                0, window_proc, 0, 0, instance, None, None,
                gdi32.CreateSolidBrush(0x000000), None, class_name,
            )
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            left, top, right, bottom = bounds
            padding = 7
            target_width, target_height = right - left, bottom - top
            overlay_width = max(target_width + padding * 2, 220 if label else 0)
            overlay_height = target_height + padding * 2 + (24 if label else 0)
            ex_style = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
            hwnd = user32.CreateWindowExW(
                ex_style, class_name, "", 0x80000000,
                left - padding, top - padding, overlay_width,
                overlay_height, None, None, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetLayeredWindowAttributes(hwnd, 0x000000, 255, 0x00000001)
            user32.SetWindowPos(
                hwnd, -1, left - padding, top - padding, overlay_width,
                overlay_height, 0x0010 | 0x0040,
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
                self._threads.discard(threading.current_thread())
