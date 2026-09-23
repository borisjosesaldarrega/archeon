"""Windows per-user startup integration with no resident helper process."""

from __future__ import annotations

import os
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ARCHEON"


def launch_command() -> str:
    """Return the packaged or development command Windows should start."""

    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    pythonw = executable.with_name("pythonw.exe")
    runner = pythonw if pythonw.is_file() else executable
    return f'"{runner}" -m archeon'


def configure_launch_at_login(enabled: bool) -> None:
    """Update only the current user's Run value; never requires elevation."""

    if os.name != "nt":
        if enabled:
            raise OSError("launch_at_login_windows_only")
        return
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
