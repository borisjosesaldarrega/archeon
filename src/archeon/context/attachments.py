"""Streaming attachment storage without placing file bodies in prompts or RAM."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO
from uuid import uuid4


MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_ATTACHMENTS_PER_REQUEST = 10
_SAFE_NAME = re.compile(r"[^\w.()\- ]+", re.UNICODE)


def _kind(name: str, content_type: str) -> str:
    suffix = Path(name).suffix.casefold()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if suffix == ".pdf" or suffix in {".doc", ".docx", ".odt", ".rtf"}:
        return "document"
    if suffix in {".xls", ".xlsx", ".ods", ".csv", ".tsv"}:
        return "data"
    if suffix in {".ppt", ".pptx", ".odp"}:
        return "presentation"
    if suffix in {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}:
        return "archive"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".toml", ".yaml", ".yml", ".md", ".sql", ".ps1", ".bat", ".cpp", ".c", ".h", ".java", ".cs", ".go", ".rs"}:
        return "code"
    if content_type.startswith("text/"):
        return "text"
    return "file"


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    id: str
    name: str
    content_type: str
    kind: str
    size: int
    path: Path
    sha256: str
    managed: bool = True

    def public(self) -> dict[str, object]:
        suffix = Path(self.name).suffix.casefold().lstrip(".") or "file"
        return {
            "id": self.id,
            "name": self.name,
            "content_type": self.content_type,
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
            "extension": suffix,
            "size_label": _size_label(self.size),
        }


def _size_label(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


@dataclass(frozen=True, slots=True)
class UserRequestContext:
    text: str
    attachments: tuple[AttachmentRecord, ...] = ()
    intent_override: str | None = None
    operational_learning_id: str | None = None

    def public(self) -> dict[str, object]:
        return {
            "text": self.text,
            "attachments": [item.public() for item in self.attachments],
            "intent_override": self.intent_override,
            "operational_learning_id": self.operational_learning_id,
        }


class AttachmentStore:
    def __init__(self, root: Path) -> None:
        self._root = root / uuid4().hex
        self._records: dict[str, AttachmentRecord] = {}
        self._lock = RLock()

    @staticmethod
    def _name(value: str) -> str:
        parts = []
        for raw in value.replace("\\", "/").split("/")[-12:]:
            if raw.strip() in {"", ".", ".."}:
                continue
            cleaned = _SAFE_NAME.sub("_", raw.strip())[:80]
            if cleaned:
                parts.append(cleaned)
        return "/".join(parts)[:240] or "attachment.bin"

    def add_stream(
        self,
        name: str,
        content_type: str,
        length: int,
        source: BinaryIO,
    ) -> AttachmentRecord:
        if length < 1 or length > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment_size_out_of_range")
        safe_name = self._name(name)
        guessed = mimetypes.guess_type(safe_name)[0]
        media_type = (content_type.split(";", 1)[0].strip() or guessed or "application/octet-stream")[:120]
        identifier = uuid4().hex
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / f"{identifier}{Path(safe_name).suffix.casefold()[:16]}"
        partial = target.with_suffix(target.suffix + ".part")
        digest = hashlib.sha256()
        remaining = length
        try:
            with partial.open("xb") as destination:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("attachment_body_incomplete")
                    destination.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        record = AttachmentRecord(
            identifier, safe_name, media_type, _kind(safe_name, media_type),
            length, target, digest.hexdigest(), True,
        )
        with self._lock:
            self._records[identifier] = record
        return record

    def resolve(self, identifiers: list[str]) -> tuple[AttachmentRecord, ...]:
        if len(identifiers) > MAX_ATTACHMENTS_PER_REQUEST:
            raise ValueError("too_many_attachments")
        with self._lock:
            try:
                records = tuple(self._records[value] for value in identifiers)
            except KeyError as error:
                raise ValueError("attachment_not_found") from error
        if any(not item.path.is_file() for item in records):
            raise ValueError("attachment_not_found")
        return records

    def remove(self, identifier: str) -> bool:
        with self._lock:
            record = self._records.pop(identifier, None)
        if record is None:
            return False
        if record.managed:
            record.path.unlink(missing_ok=True)
        return True

    def release(self, identifiers: list[str]) -> None:
        for identifier in identifiers:
            self.remove(identifier)

    def clear(self) -> None:
        with self._lock:
            identifiers = list(self._records)
        self.release(identifiers)
        try:
            self._root.rmdir()
        except OSError:
            pass
