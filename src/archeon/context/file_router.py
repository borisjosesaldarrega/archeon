"""Deterministic attachment routing without loading file bodies into the UI or prompt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .attachments import AttachmentRecord


@dataclass(frozen=True, slots=True)
class FileRoute:
    attachment_id: str
    path: Path
    category: str
    parser: str
    supported: bool

    def public(self) -> dict[str, object]:
        return {
            "attachment_id": self.attachment_id, "category": self.category,
            "parser": self.parser, "supported": self.supported,
        }


class FileTypeRouter:
    """Map verified local paths to lazy parser capabilities; never reads their contents."""

    ROUTES = {
        ".pdf": ("document", "documents.pdf"),
        ".docx": ("document", "documents.docx"),
        ".txt": ("document", "documents.text"),
        ".md": ("document", "documents.markdown"),
        ".markdown": ("document", "documents.markdown"),
        ".html": ("document", "documents.html"),
        ".htm": ("document", "documents.html"),
        ".csv": ("data", "artifacts.csv"),
        ".tsv": ("data", "artifacts.csv"),
        ".json": ("data", "artifacts.json"),
        ".xlsx": ("data", "artifacts.xlsx"),
        ".pptx": ("presentation", "artifacts.pptx"),
        ".png": ("image", "vision.image"),
        ".jpg": ("image", "vision.image"),
        ".jpeg": ("image", "vision.image"),
        ".webp": ("image", "vision.image"),
        ".bmp": ("image", "vision.image"),
        ".gif": ("image", "vision.image"),
        ".py": ("code", "programming.code"),
        ".js": ("code", "programming.code"),
        ".ts": ("code", "programming.code"),
        ".tsx": ("code", "programming.code"),
        ".jsx": ("code", "programming.code"),
        ".css": ("code", "programming.code"),
        ".sql": ("code", "programming.code"),
        ".ps1": ("code", "programming.code"),
        ".zip": ("archive", "archives.zip"),
        ".7z": ("archive", "archives.7z"),
        ".rar": ("archive", "archives.rar"),
        ".tar": ("archive", "archives.tar"),
        ".gz": ("archive", "archives.tar.gz"),
    }

    def route(self, attachment: AttachmentRecord) -> FileRoute:
        route = self.ROUTES.get(".gz" if attachment.name.casefold().endswith((".tar.gz", ".tgz")) else attachment.path.suffix.casefold())
        category, parser = route or (attachment.kind, "unsupported")
        return FileRoute(attachment.id, attachment.path, category, parser, route is not None)

    def route_many(self, attachments: Iterable[AttachmentRecord]) -> tuple[FileRoute, ...]:
        return tuple(self.route(item) for item in attachments)
