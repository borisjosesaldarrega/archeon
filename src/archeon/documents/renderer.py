"""Optional, on-demand page preview; never loaded by document text extraction."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class DocumentRenderer:
    def render_pdf_page(self, path: str | Path, page: int, output: str | Path) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        destination = Path(output).expanduser().resolve()
        if target.suffix.casefold() != ".pdf" or not target.is_file():
            raise ValueError("pdf_document_required")
        if page < 1:
            raise ValueError("invalid_page_number")
        executable = shutil.which("pdftoppm")
        if not executable:
            raise RuntimeError("pdf_preview_provider_not_installed")
        if not destination.parent.is_dir():
            raise FileNotFoundError("preview_output_folder_not_found")
        with tempfile.TemporaryDirectory(prefix="archeon-preview-") as folder:
            prefix = Path(folder) / "page"
            completed = subprocess.run(
                [executable, "-f", str(page), "-singlefile", "-png", "-r", "120", str(target), str(prefix)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False,
            )
            generated = prefix.with_suffix(".png")
            if completed.returncode != 0 or not generated.is_file():
                raise RuntimeError("pdf_preview_failed")
            shutil.copy2(generated, destination)
        return {"path": str(target), "page": page, "preview": str(destination), "verified": destination.is_file()}
