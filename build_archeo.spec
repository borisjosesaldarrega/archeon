# -*- mode: python ; coding: utf-8 -*-
"""Lean one-folder build for the modular ARCHEON 10 Core.

The installer remains a single compressed executable, while the installed app
avoids PyInstaller's per-launch extraction process and its temporary parent.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "src" / "archeon" / "ui"), "archeon/ui"),
]
binaries = collect_dynamic_libs("vosk")
hiddenimports = [
    "webview",
    "webview.platforms.winforms",
    "sounddevice",
    "vosk",
    "webrtcvad",
    "comtypes",
    "comtypes.client",
    "miniaudio",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageOps",
    "PIL.ImageTk",
    "tinytag",
]

a = Analysis(
    [str(ROOT / "src" / "archeon" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[str(ROOT / "tools" / "pyinstaller-hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6", "flask", "firebase_admin",
        "google.cloud", "google.generativeai", "numpy", "pandas", "torch",
        "tensorflow", "cv2", "pyautogui", "yt_dlp", "speech_recognition",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Archeo32n",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "web" / "logo_asitente.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Archeo32n",
)
