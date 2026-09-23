"""Archive intelligence layered on the stable native archive provider."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .archive import ArchiveEngineProvider as _BaselineArchiveEngine


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: str
    bytes: int
    compressed_bytes: int | None
    directory: bool
    extension: str
    encrypted: bool = False
    risk: str = "data"

    def public(self) -> dict[str, Any]: return asdict(self)


class ArchiveInspector:
    """Build a bounded index and risk assessment without extracting contents."""

    EXECUTABLES = {".exe", ".com", ".msi", ".dll", ".scr"}
    SCRIPTS = {".bat", ".cmd", ".ps1", ".vbs", ".jse", ".wsf", ".hta"}
    MACROS = {".docm", ".xlsm", ".pptm"}
    WEB = {".html", ".htm", ".css", ".js", ".mjs"}

    @classmethod
    def classify(cls, name: str) -> str:
        suffix = Path(name).suffix.casefold()
        if suffix in cls.EXECUTABLES: return "executable"
        if suffix in cls.SCRIPTS: return "script"
        if suffix in cls.MACROS: return "macro_document"
        if suffix in cls.WEB: return "web_content"
        return "data"

    @staticmethod
    def tree(entries: Iterable[ArchiveEntry], root_name: str) -> str:
        root: dict[str, Any] = {}
        for entry in entries:
            cursor = root
            for part in PurePosixPath(entry.path.replace("\\", "/")).parts:
                if part not in {"", "."}: cursor = cursor.setdefault(part, {})
        lines = [root_name]
        def visit(node: dict[str, Any], prefix: str) -> None:
            names = sorted(node, key=lambda item: (bool(node[item]), item.casefold()))
            for index, name in enumerate(names):
                last = index == len(names) - 1
                lines.append(f"{prefix}{'└── ' if last else '├── '}{name}")
                if node[name]: visit(node[name], prefix + ("    " if last else "│   "))
        visit(root, "")
        return "\n".join(lines)


class NativeZipProvider:
    kind = "zip"
    @staticmethod
    def entries(source: Path) -> list[ArchiveEntry]:
        with zipfile.ZipFile(source) as archive:
            return [ArchiveEntry(item.filename, item.file_size, item.compress_size, item.is_dir(), Path(item.filename).suffix.casefold(), bool(item.flag_bits & 1), ArchiveInspector.classify(item.filename)) for item in archive.infolist()]
    @staticmethod
    def read(source: Path, member: str, password: str | None, limit: int) -> bytes:
        with zipfile.ZipFile(source) as archive:
            info = archive.getinfo(member)
            if info.is_dir() or info.file_size > limit: raise ValueError("archive_member_too_large_to_read")
            try:
                with archive.open(info, pwd=password.encode() if password else None) as stream: data = stream.read(limit + 1)
            except RuntimeError as error: raise ValueError("archive_password_required_or_invalid") from error
        if len(data) > limit: raise ValueError("archive_member_too_large_to_read")
        return data


class NativeTarProvider:
    kind = "tar"
    @staticmethod
    def entries(source: Path) -> list[ArchiveEntry]:
        with tarfile.open(source, "r:*") as archive:
            return [ArchiveEntry(item.name, item.size, None, item.isdir(), Path(item.name).suffix.casefold(), False, ArchiveInspector.classify(item.name)) for item in archive.getmembers()]
    @staticmethod
    def read(source: Path, member: str, password: str | None, limit: int) -> bytes:
        del password
        with tarfile.open(source, "r:*") as archive:
            info = archive.getmember(member)
            if not info.isfile() or info.size > limit: raise ValueError("archive_member_too_large_to_read")
            stream = archive.extractfile(info)
            if stream is None: raise ValueError("archive_member_not_readable")
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError("archive_member_too_large_to_read")
        return data


@dataclass(frozen=True, slots=True)
class SevenZipProvider:
    executable: Path | None
    bundled: bool = False


@dataclass(frozen=True, slots=True)
class RarProvider:
    executable: Path | None
    bundled: bool = False
    licensed_provider_required: bool = True


class ArchiveEngineProvider(_BaselineArchiveEngine):
    """Provider facade: native ZIP/TAR and isolated optional 7Z/RAR."""

    MAX_MEMBER_READ_BYTES = 8 * 1024 * 1024
    MAX_COMPRESSION_RATIO = 250.0

    def __init__(self) -> None:
        self.native_zip = NativeZipProvider(); self.native_tar = NativeTarProvider()
        self.seven_zip = SevenZipProvider(self._find_executable("7z")); self.rar = RarProvider(self._find_executable("rar"))

    def list(self, archive_path: str | Path) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve()
        if not source.is_file(): raise FileNotFoundError("archive_not_found")
        kind = self._kind(source)
        if kind == "zip": entries = self.native_zip.entries(source)
        elif kind in {"tar", "tar.gz"}: entries = self.native_tar.entries(source)
        else: entries = self._optional_entries(source, kind)
        if len(entries) > self.MAX_MEMBERS: raise ValueError("archive_member_limit_exceeded")
        names = [entry.path.replace("\\", "/").casefold() for entry in entries]
        expected = sum(entry.bytes for entry in entries if not entry.directory); compressed = source.stat().st_size
        ratio = expected / max(1, compressed); warnings: list[str] = []
        if expected > self.MAX_EXTRACTED_BYTES: warnings.append("extracted_size_limit")
        if ratio > self.MAX_COMPRESSION_RATIO: warnings.append("suspicious_compression_ratio")
        if len(names) != len(set(names)): warnings.append("duplicate_paths")
        for entry in entries:
            try: self._safe_member(entry.path)
            except ValueError: warnings.append("unsafe_path"); break
        risk_counts: dict[str, int] = {}
        for entry in entries:
            if not entry.directory: risk_counts[entry.risk] = risk_counts.get(entry.risk, 0) + 1
        members = [entry.public() | {"name": entry.path} for entry in entries]
        return {"path": str(source), "format": kind, "members": members, "member_count": len(entries), "file_count": sum(not item.directory for item in entries), "folder_count": sum(item.directory for item in entries), "total_bytes": expected, "compressed_bytes": compressed, "compression_ratio": round(ratio, 3), "encrypted": any(item.encrypted for item in entries), "risk_counts": risk_counts, "warnings": sorted(set(warnings)), "safe_to_extract": not warnings, "tree": ArchiveInspector.tree(entries, source.name)}

    inspect = list

    def analyze_project(self, archive_path: str | Path) -> dict[str, Any]:
        """Recognize common project structures using bounded static inspection."""
        listing = self.list(archive_path); names = [str(item["path"]).replace("\\", "/") for item in listing["members"] if not item["directory"]]
        folded = {name.casefold(): name for name in names}; basenames = {PurePosixPath(name).name.casefold(): name for name in names}
        signals: list[str] = []; stack: list[str] = []; entrypoints: list[str] = []
        if "package.json" in basenames:
            signals.append("package.json"); package = self.read_member(archive_path, basenames["package.json"], max_bytes=512 * 1024)
            try:
                payload = json.loads(str(package.get("text", "{}"))); dependencies = {**payload.get("dependencies", {}), **payload.get("devDependencies", {})}
                for key, label in (("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"), ("next", "Next.js"), ("vite", "Vite"), ("express", "Express")):
                    if key in dependencies: stack.append(label)
            except (TypeError, ValueError, json.JSONDecodeError): signals.append("package_json_invalid")
        if any(name.casefold().startswith("src/") or "/src/" in name.casefold() for name in names): signals.append("src_directory")
        if any(name.casefold().startswith("public/") or "/public/" in name.casefold() for name in names): signals.append("public_directory")
        for candidate in ("index.html", "main.py", "app.py", "manage.py", "cargo.toml", "pyproject.toml"):
            if candidate in basenames: entrypoints.append(basenames[candidate])
        if "pyproject.toml" in basenames or "requirements.txt" in basenames: stack.append("Python")
        if "cargo.toml" in basenames: stack.append("Rust")
        if any(Path(name).suffix.casefold() in {".html", ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx"} for name in names): stack.append("Web")
        project_type = "web_project" if "Web" in stack or {"src_directory", "public_directory"}.issubset(signals) else "software_project" if stack else "file_collection"
        return {"path": listing["path"], "project_type": project_type, "stack": list(dict.fromkeys(stack)), "signals": signals, "entrypoints": entrypoints, "member_count": listing["member_count"], "static_only": True, "executed": False, "safe_to_extract": listing["safe_to_extract"], "warnings": listing["warnings"]}

    def read_member(self, archive_path: str | Path, member: str, *, password: str | None = None, max_bytes: int | None = None) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve(); self._safe_member(member); listing = self.list(source)
        entry = next((item for item in listing["members"] if item["path"] == member and not item["directory"]), None)
        if entry is None: raise FileNotFoundError("archive_member_not_found")
        limit = min(max(1, int(max_bytes or self.MAX_MEMBER_READ_BYTES)), self.MAX_MEMBER_READ_BYTES); kind = listing["format"]
        if kind == "zip": data = self.native_zip.read(source, member, password, limit)
        elif kind in {"tar", "tar.gz"}: data = self.native_tar.read(source, member, password, limit)
        else: data = self._optional_read(source, kind, member, password, limit)
        textual = Path(member).suffix.casefold() in {".txt", ".md", ".json", ".csv", ".tsv", ".html", ".htm", ".css", ".js", ".mjs", ".py", ".xml", ".yaml", ".yml"}
        return {"archive": str(source), "member": member, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "risk": entry["risk"], "textual": textual, "text": data.decode("utf-8-sig", errors="replace") if textual else None, "executed": False}

    def extract(self, archive_path: str | Path, destination: str | Path, *, members: Iterable[str] | None = None, password: str | None = None) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve(); target = Path(destination).expanduser().resolve()
        if target.exists() or not target.parent.is_dir(): raise ValueError("archive_extract_target_must_be_new")
        listing = self.list(source)
        if "unsafe_path" in listing["warnings"]: raise ValueError("archive_path_traversal_rejected")
        if not listing["safe_to_extract"]: raise ValueError("archive_security_limits_exceeded:" + ",".join(listing["warnings"]))
        selected = list(dict.fromkeys(str(value) for value in (members or ())))
        available = {item["path"] for item in listing["members"]}
        if selected and any(value not in available for value in selected): raise FileNotFoundError("archive_member_not_found")
        for name in selected or available: self._safe_member(name)
        target.mkdir()
        try:
            kind = listing["format"]
            if kind == "zip": self._extract_zip(source, target, selected, password)
            elif kind in {"tar", "tar.gz"}: self._extract_tar(source, target, selected)
            else: self._extract_optional(source, target, kind, selected, password)
            files = [item for item in target.rglob("*") if item.is_file()]
            expected = sum(not item["directory"] and (not selected or item["path"] in selected) for item in listing["members"])
            return {"archive": str(source), "destination": str(target), "files": len(files), "verified": len(files) == expected, "selective": bool(selected), "hashes": {str(item.relative_to(target)).replace("\\", "/"): self._sha256_file(item) for item in files}}
        except BaseException:
            shutil.rmtree(target, ignore_errors=True); raise

    def extract_selected(self, archive_path: str | Path, destination: str | Path, members: Iterable[str], *, password: str | None = None) -> dict[str, Any]:
        return self.extract(archive_path, destination, members=members, password=password)

    def verify(self, archive_path: str | Path) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve(); kind = self._kind(source); listing = self.list(source)
        if kind == "zip":
            with zipfile.ZipFile(source) as archive: integrity = archive.testzip() is None
        elif kind in {"tar", "tar.gz"}:
            with tarfile.open(source, "r:*") as archive: integrity = all(item.name for item in archive.getmembers())
        else:
            executable = self._require_executable(kind); self._run([str(executable), "t", str(source)]); integrity = True
        listing.update({"valid": bool(integrity), "bytes": source.stat().st_size, "sha256": self._sha256_file(source)}); return listing

    def _optional_entries(self, source: Path, kind: str) -> list[ArchiveEntry]:
        executable = self._require_executable(kind)
        if kind != "7z":
            output = self._run([str(executable), "lt", "-scu", str(source)])
            names = [line.strip() for line in output.splitlines() if line.strip().casefold().endswith((".txt", ".md", ".html", ".js", ".css", ".pdf", ".docx", ".xlsx", ".pptx"))]
            return [ArchiveEntry(name, 0, None, False, Path(name).suffix.casefold(), False, ArchiveInspector.classify(name)) for name in names]
        output = self._run([str(executable), "l", "-slt", str(source)]); entries: list[ArchiveEntry] = []
        for block in output.replace("\r", "").split("\n\n")[1:]:
            fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line); name = fields.get("Path")
            if name: entries.append(ArchiveEntry(name, int(fields.get("Size", 0) or 0), int(fields.get("Packed Size", 0) or 0), fields.get("Folder") == "+", Path(name).suffix.casefold(), fields.get("Encrypted") == "+", ArchiveInspector.classify(name)))
        return entries

    def _optional_read(self, source: Path, kind: str, member: str, password: str | None, limit: int) -> bytes:
        executable = self._require_executable(kind); process = subprocess.run([str(executable), "e", "-so", f"-p{password}" if password else "-p-", str(source), member], capture_output=True, timeout=60, shell=False)
        if process.returncode != 0:
            if b"password" in process.stderr.casefold(): raise ValueError("archive_password_required_or_invalid")
            raise RuntimeError(f"archive_provider_failed:{process.returncode}")
        if len(process.stdout) > limit: raise ValueError("archive_member_too_large_to_read")
        return process.stdout

    @staticmethod
    def _extract_zip(source: Path, target: Path, selected: list[str], password: str | None) -> None:
        with zipfile.ZipFile(source) as archive:
            infos = [archive.getinfo(name) for name in selected] if selected else archive.infolist()
            for info in infos:
                if (info.external_attr >> 16) & 0o170000 == 0o120000: raise ValueError("archive_symlink_rejected")
                archive.extract(info, target, pwd=password.encode() if password else None)
    @staticmethod
    def _extract_tar(source: Path, target: Path, selected: list[str]) -> None:
        with tarfile.open(source, "r:*") as archive:
            infos = [archive.getmember(name) for name in selected] if selected else archive.getmembers()
            if any(item.issym() or item.islnk() or item.isdev() for item in infos): raise ValueError("archive_link_or_device_rejected")
            archive.extractall(target, members=infos, filter="data")
    def _extract_optional(self, source: Path, target: Path, kind: str, selected: list[str], password: str | None) -> None:
        executable = self._require_executable(kind); self._run([str(executable), "x", "-y", f"-p{password}" if password else "-p-", f"-o{target}", str(source), *selected])
    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()
