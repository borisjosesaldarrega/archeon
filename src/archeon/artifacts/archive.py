"""Safe native archives plus isolated optional 7Z/RAR executable providers."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class ArchiveEngineProvider:
    MAX_MEMBERS = 20_000
    MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024

    def capabilities(self) -> dict[str, Any]:
        seven = self._find_executable("7z")
        rar = self._find_executable("rar")
        return {
            "zip": {"available": True, "provider": "python_stdlib", "licensed": True},
            "tar": {"available": True, "provider": "python_stdlib", "licensed": True},
            "tar.gz": {"available": True, "provider": "python_stdlib", "licensed": True},
            "7z": {"available": bool(seven), "provider": str(seven or "optional_7zip"), "bundled": False},
            "rar": {"available": bool(rar), "provider": str(rar or "licensed_winrar_required"), "bundled": False, "licensed_provider_required": True},
        }

    def create(self, destination: str | Path, sources: Iterable[str | Path]) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve()
        source_paths = [Path(item).expanduser().resolve() for item in sources]
        if target.exists() or not target.parent.is_dir() or not source_paths:
            raise ValueError("archive_create_paths_invalid")
        if any(not item.exists() for item in source_paths):
            raise FileNotFoundError("archive_source_missing")
        kind = self._kind(target)
        if kind == "zip":
            with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                self._add_zip(archive, source_paths)
        elif kind in {"tar", "tar.gz"}:
            with tarfile.open(target, "x:gz" if kind == "tar.gz" else "x:") as archive:
                for source in source_paths:
                    archive.add(source, arcname=source.name, recursive=True)
        elif kind == "7z":
            executable = self._require_executable("7z")
            self._run([str(executable), "a", "-t7z", "-mx=5", str(target), *map(str, source_paths)])
        elif kind == "rar":
            executable = self._require_executable("rar")
            self._run([str(executable), "a", "-ep1", str(target), *map(str, source_paths)])
        result = self.verify(target); result["created"] = True
        return result

    def list(self, archive_path: str | Path) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError("archive_not_found")
        kind = self._kind(source)
        members: list[dict[str, Any]] = []
        if kind == "zip":
            with zipfile.ZipFile(source) as archive:
                members = [{"name": item.filename, "bytes": item.file_size, "directory": item.is_dir()} for item in archive.infolist()]
        elif kind in {"tar", "tar.gz"}:
            with tarfile.open(source, "r:*") as archive:
                members = [{"name": item.name, "bytes": item.size, "directory": item.isdir()} for item in archive.getmembers()]
        else:
            executable = self._require_executable(kind)
            output = self._run([str(executable), "l", "-slt", str(source)]) if kind == "7z" else self._run([str(executable), "lt", str(source)])
            members = [{"name": line.split(" = ", 1)[1], "bytes": 0, "directory": False} for line in output.splitlines() if line.startswith("Path = ")][1:]
        if len(members) > self.MAX_MEMBERS:
            raise ValueError("archive_member_limit_exceeded")
        return {"path": str(source), "format": kind, "members": members, "member_count": len(members), "total_bytes": sum(int(item["bytes"]) for item in members)}

    def verify(self, archive_path: str | Path) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve(); kind = self._kind(source)
        listing = self.list(source)
        if kind == "zip":
            with zipfile.ZipFile(source) as archive:
                integrity = archive.testzip() is None
        elif kind in {"tar", "tar.gz"}:
            with tarfile.open(source, "r:*") as archive:
                integrity = all(member.name for member in archive.getmembers())
        else:
            executable = self._require_executable(kind)
            self._run([str(executable), "t", str(source)]); integrity = True
        listing.update({
            "valid": bool(integrity), "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        })
        return listing

    def extract(self, archive_path: str | Path, destination: str | Path) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve()
        target = Path(destination).expanduser().resolve()
        if target.exists() or not target.parent.is_dir():
            raise ValueError("archive_extract_target_must_be_new")
        listing = self.list(source)
        if listing["total_bytes"] > self.MAX_EXTRACTED_BYTES:
            raise ValueError("archive_extracted_size_limit_exceeded")
        for member in listing["members"]:
            self._safe_member(str(member["name"]))
        target.mkdir()
        try:
            kind = listing["format"]
            if kind == "zip":
                with zipfile.ZipFile(source) as archive:
                    for info in archive.infolist():
                        if (info.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("archive_symlink_rejected")
                    archive.extractall(target)
            elif kind in {"tar", "tar.gz"}:
                with tarfile.open(source, "r:*") as archive:
                    if any(item.issym() or item.islnk() or item.isdev() for item in archive.getmembers()):
                        raise ValueError("archive_link_or_device_rejected")
                    archive.extractall(target, filter="data")
            else:
                executable = self._require_executable(kind)
                self._run([str(executable), "x", "-y", f"-o{target}", str(source)])
            extracted = [item for item in target.rglob("*") if item.is_file()]
            expected_files = sum(not bool(item["directory"]) for item in listing["members"])
            return {"archive": str(source), "destination": str(target), "files": len(extracted), "verified": len(extracted) == expected_files}
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise

    @staticmethod
    def _add_zip(archive: zipfile.ZipFile, sources: list[Path]) -> None:
        for source in sources:
            if source.is_file():
                archive.write(source, source.name)
            else:
                for item in source.rglob("*"):
                    if item.is_symlink():
                        raise ValueError("archive_symlink_rejected")
                    if item.is_file():
                        archive.write(item, str(Path(source.name) / item.relative_to(source)))

    @staticmethod
    def _safe_member(name: str) -> None:
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise ValueError("archive_path_traversal_rejected")

    @staticmethod
    def _kind(path: Path) -> str:
        name = path.name.casefold()
        if name.endswith((".tar.gz", ".tgz")): return "tar.gz"
        if name.endswith(".tar"): return "tar"
        if name.endswith(".zip"): return "zip"
        if name.endswith(".7z"): return "7z"
        if name.endswith(".rar"): return "rar"
        raise ValueError("unsupported_archive_format")

    @staticmethod
    def _find_executable(kind: str) -> Path | None:
        names = ["7z.exe", "7zz.exe"] if kind == "7z" else ["Rar.exe", "WinRAR.exe"]
        fixed = [Path("C:/Program Files/7-Zip/7z.exe")] if kind == "7z" else [Path("C:/Program Files/WinRAR/Rar.exe"), Path("C:/Program Files/WinRAR/WinRAR.exe")]
        for candidate in fixed:
            if candidate.is_file(): return candidate
        for name in names:
            resolved = shutil.which(name)
            if resolved: return Path(resolved)
        return None

    def _require_executable(self, kind: str) -> Path:
        executable = self._find_executable(kind)
        if executable is None:
            raise RuntimeError(f"archive_{kind}_optional_provider_unavailable")
        return executable

    @staticmethod
    def _run(command: list[str]) -> str:
        process = subprocess.run(command, capture_output=True, text=True, timeout=180, shell=False)
        if process.returncode != 0:
            raise RuntimeError(f"archive_provider_failed:{process.returncode}:{process.stderr[-500:]}")
        return process.stdout
