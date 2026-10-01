# -*- mode: python ; coding: utf-8 -*-
"""Lean one-folder build for the consolidated ARCHEON Core.

The installer remains a single compressed executable, while the installed app
avoids PyInstaller's per-launch extraction process and its temporary parent.
"""

import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# Generate the small Windows UI Automation wrappers at build time so packaged
# ARCHI observation never needs to write Python modules on the user's machine.
from comtypes.client import GetModule
GetModule("UIAutomationCore.dll")


ROOT = Path(SPECPATH)


def public_cloud_config() -> Path:
    values = {}
    for source in (ROOT / ".env", ROOT / ".env.local"):
        if not source.is_file():
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            if key in {"ARCHEON_SUPABASE_URL", "ARCHEON_SUPABASE_PUBLISHABLE_KEY"}:
                values[key] = value.strip().strip('"').strip("'")
    target = ROOT / "build" / "archeon-public-cloud.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(values, separators=(",", ":")), encoding="utf-8")
    return target


datas = [
    (str(ROOT / "src" / "archeon" / "ui"), "archeon/ui"),
    (str(ROOT / "assets" / "ARCHEON.mp4"), "archeon/ui"),
    (str(public_cloud_config()), "archeon"),
]
binaries = collect_dynamic_libs("vosk")
hiddenimports = [
    "webview",
    "webview.platforms.winforms",
    "pystray",
    "pystray._win32",
    "sounddevice",
    "vosk",
    "webrtcvad",
    "comtypes",
    "comtypes.client",
    "comtypes.gen.UIAutomationClient",
    "miniaudio",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageOps",
    "PIL.ImageTk",
    "tinytag",
    "yt_dlp",
    "pypdf",
    "docx",
    "docx.oxml",
    "openpyxl",
    "pptx",
    "lxml.etree",
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
        "tensorflow", "cv2", "pyautogui", "speech_recognition",
        # Ghost needs basic PNG/JPEG/WebP raster support, not AVIF, FreeType,
        # color-management, or Pillow's numerical imaging extension.
        "PIL._avif", "PIL._imagingft", "PIL._imagingcms", "PIL._imagingmath",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ARCHEON",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "logo_asitente.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="ARCHEON",
)
