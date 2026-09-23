"""On-demand native Windows pickers without a resident Tcl interpreter."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Final


_FILE_DIALOG: Final[str] = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = $env:ARCHEON_DIALOG_TITLE
$dialog.Filter = $env:ARCHEON_DIALOG_FILTER
$dialog.Multiselect = $env:ARCHEON_DIALOG_MULTI -eq '1'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @($dialog.FileNames) | ConvertTo-Json -Compress
}
$dialog.Dispose()
"""

_FOLDER_DIALOG: Final[str] = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:ARCHEON_DIALOG_TITLE
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}
$dialog.Dispose()
"""


def _run_picker(script: str, *, title: str, file_filter: str = "", multiple: bool = False) -> list[str]:
    if os.name != "nt":
        raise RuntimeError("native_windows_dialog_unavailable")
    environment = os.environ.copy()
    environment.update({
        "ARCHEON_DIALOG_TITLE": title,
        "ARCHEON_DIALOG_FILTER": file_filter,
        "ARCHEON_DIALOG_MULTI": "1" if multiple else "0",
    })
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError("native_dialog_failed")
    output = result.stdout.strip().lstrip("\ufeff")
    if not output:
        return []
    value = json.loads(output)
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if str(item)]


def choose_audio_files() -> list[str]:
    return _run_picker(
        _FILE_DIALOG,
        title="Elegir música para ARCHEON",
        file_filter="Audio compatible|*.mp3;*.wav;*.flac;*.ogg|Todos los archivos|*.*",
        multiple=True,
    )


def choose_visual_file(kind: str) -> str | None:
    choices = {
        "image": "Imágenes|*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp|Todos los archivos|*.*",
        "video": "Videos|*.mp4;*.webm;*.m4v|Todos los archivos|*.*",
        "logo": "Logo animado o imagen|*.png;*.jpg;*.jpeg;*.webp;*.gif;*.mp4;*.webm;*.m4v|Todos los archivos|*.*",
        "chat": "Fondo del chat|*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp|Todos los archivos|*.*",
    }
    if kind not in choices:
        raise ValueError("invalid_visual_kind")
    selected = _run_picker(_FILE_DIALOG, title="Personalizar ARCHEON", file_filter=choices[kind])
    return selected[0] if selected else None


def choose_directory(title: str) -> str | None:
    selected = _run_picker(_FOLDER_DIALOG, title=title)
    return selected[0] if selected else None


def choose_launcher_target() -> str | None:
    selected = _run_picker(
        _FILE_DIALOG,
        title="Añadir aplicación, juego o atajo a ARCHEON",
        file_filter="Aplicaciones y atajos|*.exe;*.lnk;*.url;*.appref-ms;*.bat;*.cmd|Todos los archivos|*.*",
    )
    return selected[0] if selected else None
