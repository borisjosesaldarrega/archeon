"""Small, synchronous Windows clipboard access with no history or logging."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


class WindowsClipboard:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    def __init__(self, owner_handle: int = 0) -> None:
        self.owner_handle = owner_handle

    @staticmethod
    def _apis() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetClipboardData.argtypes = (wintypes.UINT,)
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = (wintypes.HANDLE,)
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = (wintypes.HANDLE,)
        kernel32.GlobalFree.argtypes = (wintypes.HANDLE,)
        return user32, kernel32

    def _open(self, user32: ctypes.WinDLL) -> None:
        for attempt in range(8):
            if user32.OpenClipboard(self.owner_handle):
                return
            if attempt < 7:
                time.sleep(0.015 * (attempt + 1))
        raise ctypes.WinError(ctypes.get_last_error())

    def read_text(self) -> str:
        user32, kernel32 = self._apis()
        self._open(user32)
        try:
            handle = user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def write_text(self, text: str) -> None:
        user32, kernel32 = self._apis()
        encoded = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(encoded))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(pointer, encoded, len(encoded))
        kernel32.GlobalUnlock(handle)
        try:
            self._open(user32)
        except BaseException:
            kernel32.GlobalFree(handle)
            raise
        transferred = False
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetClipboardData(self.CF_UNICODETEXT, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            transferred = True
        finally:
            user32.CloseClipboard()
            if not transferred:
                kernel32.GlobalFree(handle)

    def clear(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._open(user32)
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            user32.CloseClipboard()
