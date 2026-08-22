"""Small, lazy metadata and embedded-art reader."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    path: Path | str
    title: str
    artist: str
    album: str
    duration_ms: int
    artwork_id: str | None = None
    artwork_url: str | None = None
    provider: str = "local"
    source_url: str | None = None
    license_url: str | None = None

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_ms": self.duration_ms,
            "artwork_url": f"/media/art/{self.artwork_id}" if self.artwork_id else self.artwork_url,
            "provider": self.provider,
            "source_url": self.source_url,
            "license_url": self.license_url,
        }


class MetadataReader:
    MAX_ART_BYTES = 4 * 1024 * 1024

    def __init__(self, artwork_dir: Path) -> None:
        self._artwork_dir = artwork_dir
        self._artwork: dict[str, tuple[Path, str]] = {}

    @staticmethod
    def _first(value: object, fallback: str = "") -> str:
        if isinstance(value, (list, tuple)):
            return str(value[0]) if value else fallback
        return str(value) if value else fallback

    def read(self, path: Path) -> Track:
        from tinytag import TinyTag

        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("media_path_is_not_a_file")
        tag = TinyTag.get(str(resolved), image=True)
        digest = hashlib.sha256(str(resolved).encode("utf-8") + str(resolved.stat().st_mtime_ns).encode()).hexdigest()
        artwork_id = None
        image = tag.images.any
        if image is not None and 0 < image.size <= self.MAX_ART_BYTES:
            artwork_id = digest[:24]
            mime = image.mime_type or "image/jpeg"
            suffix = {"image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
            self._artwork_dir.mkdir(parents=True, exist_ok=True)
            target = self._artwork_dir / f"{artwork_id}{suffix}"
            if not target.exists():
                with NamedTemporaryFile("wb", dir=self._artwork_dir, delete=False) as temporary:
                    temporary.write(image.data)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temp_path = Path(temporary.name)
                os.replace(temp_path, target)
            self._artwork[artwork_id] = (target, mime)
        return Track(
            id=digest[:24],
            path=resolved,
            title=self._first(tag.title, resolved.stem),
            artist=self._first(tag.artist, "Artista local"),
            album=self._first(tag.album),
            duration_ms=max(0, round((tag.duration or 0.0) * 1000)),
            artwork_id=artwork_id,
        )

    def artwork(self, artwork_id: str) -> tuple[str, bytes] | None:
        item = self._artwork.get(artwork_id)
        if item is None:
            return None
        path, mime = item
        try:
            return mime, path.read_bytes()
        except OSError:
            return None
