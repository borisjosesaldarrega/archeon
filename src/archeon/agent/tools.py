"""Bounded file and terminal tools used by ARCHI plans."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.events import EventBus
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult


FILE_LIST_MANIFEST = ToolManifest(
    id="files.list", description="List a bounded local folder", permissions=("filesystem.read",),
    risk=RiskLevel.READ_ONLY, timeout_seconds=10.0,
)
FILE_SEARCH_MANIFEST = ToolManifest(
    id="files.search", description="Search within one explicit local folder", permissions=("filesystem.read",),
    risk=RiskLevel.READ_ONLY, timeout_seconds=15.0,
)
FILE_READ_MANIFEST = ToolManifest(
    id="files.read", description="Read one explicit bounded text file", permissions=("filesystem.read",),
    risk=RiskLevel.READ_ONLY, timeout_seconds=10.0,
)
FOLDER_CREATE_MANIFEST = ToolManifest(
    id="files.create_folder", description="Create one explicit local folder", permissions=("filesystem.write",),
    risk=RiskLevel.LOW, timeout_seconds=10.0, supports_rollback=True, checkpoint_policy="record-created-path",
)
FILE_ENSURE_MANIFEST = ToolManifest(
    id="files.ensure_empty", description="Create a new empty file without overwriting existing data",
    permissions=("filesystem.write",), risk=RiskLevel.LOW, timeout_seconds=10.0,
    supports_rollback=True, checkpoint_policy="record-created-path",
)
FILE_VERIFY_TEXT_MANIFEST = ToolManifest(
    id="files.verify_text", description="Verify exact text in one explicit file",
    permissions=("filesystem.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=10.0,
)
TERMINAL_RUN_MANIFEST = ToolManifest(
    id="terminal.run", description="Run a validated bounded terminal command", permissions=("terminal.execute",),
    risk=RiskLevel.MEDIUM, timeout_seconds=60.0, checkpoint_policy="before-write-command",
)
TERMINAL_CANCEL_MANIFEST = ToolManifest(
    id="terminal.cancel", description="Cancel the active bounded terminal command and its process tree",
    permissions=("terminal.execute",), risk=RiskLevel.LOW, timeout_seconds=15.0,
)


def _path(value: Any) -> Path:
    if not str(value or "").strip():
        raise ValueError("path_required")
    return Path(str(value)).expanduser().resolve()


def _entry(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name, "path": str(path), "kind": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else None, "modified": stat.st_mtime,
    }


class ListFolderTool:
    manifest = FILE_LIST_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        root = _path(arguments.get("path"))
        if not root.is_dir():
            return ToolResult(False, error="folder_not_found", error_code="not_found")
        limit = max(1, min(int(arguments.get("limit", 200)), 1000))
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))[:limit]
        data = {"path": str(root), "entries": [_entry(item) for item in entries], "truncated": len(entries) == limit}
        return ToolResult(True, data, evidence={"folder_exists": root.is_dir(), "entries": len(entries)})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.data.get("path") and result.evidence.get("folder_exists"))


class SearchFilesTool:
    manifest = FILE_SEARCH_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        root = _path(arguments.get("path"))
        if not root.is_dir():
            return ToolResult(False, error="folder_not_found", error_code="not_found")
        if root == Path(root.anchor):
            return ToolResult(False, error="drive_root_search_not_allowed", error_code="scope_too_broad")
        query = str(arguments.get("query", "")).casefold().strip()
        extension = str(arguments.get("extension", "")).casefold().strip().lstrip(".")
        limit = max(1, min(int(arguments.get("limit", 50)), 200))
        recursive = bool(arguments.get("recursive", True))
        iterator = root.rglob("*") if recursive else root.iterdir()
        matches: list[Path] = []
        visited = 0
        for item in iterator:
            visited += 1
            if visited > 5000:
                break
            if query and query not in item.name.casefold():
                continue
            if extension and (not item.is_file() or item.suffix.casefold().lstrip(".") != extension):
                continue
            matches.append(item)
            if len(matches) >= limit:
                break
        matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        data = {
            "path": str(root), "results": [_entry(item) for item in matches],
            "visited": visited, "truncated": visited > 5000 or len(matches) == limit,
        }
        return ToolResult(True, data, evidence={"root_exists": True, "matches": len(matches)})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("root_exists") and "results" in result.data)


class ReadTextFileTool:
    manifest = FILE_READ_MANIFEST
    TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".tsv", ".html", ".htm", ".xml", ".py", ".js", ".css", ".toml", ".ini", ".yaml", ".yml", ".log"}

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        path = _path(arguments.get("path"))
        if not path.is_file():
            return ToolResult(False, error="file_not_found", error_code="not_found")
        if path.suffix.casefold() not in self.TEXT_EXTENSIONS:
            return ToolResult(False, error="unsupported_document_type", error_code="unsupported_format")
        max_bytes = max(1024, min(int(arguments.get("max_bytes", 512 * 1024)), 2 * 1024 * 1024))
        raw = path.read_bytes()
        truncated = len(raw) > max_bytes
        content = raw[:max_bytes].decode("utf-8", errors="replace")
        return ToolResult(
            True, {"path": str(path), "content": content, "truncated": truncated, "bytes": len(raw)},
            evidence={"file_exists": True, "bytes_read": min(len(raw), max_bytes)},
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("file_exists") and "content" in result.data)


class CreateFolderTool:
    manifest = FOLDER_CREATE_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        path = _path(arguments.get("path"))
        existed = path.exists()
        if existed and not path.is_dir():
            return ToolResult(False, error="path_is_not_folder", error_code="path_conflict")
        if bool(arguments.get("parents", False)):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(exist_ok=True)
        data = {"path": str(path), "created": not existed, "changed_state": not existed}
        return ToolResult(
            True, data, evidence={"folder_exists": path.is_dir()}, changed_state=not existed,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("folder_exists"))


class EnsureEmptyFileTool:
    manifest = FILE_ENSURE_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        path = _path(arguments.get("path"))
        if path.exists():
            return ToolResult(False, error="target_file_already_exists", error_code="path_conflict")
        if not path.parent.is_dir():
            return ToolResult(False, error="parent_folder_not_found", error_code="not_found")
        path.touch(exist_ok=False)
        return ToolResult(
            True, {"path": str(path), "created": True},
            evidence={"file_exists": path.is_file(), "size": path.stat().st_size}, changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("file_exists") and result.evidence.get("size") == 0)


class VerifyFileTextTool:
    manifest = FILE_VERIFY_TEXT_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        path = _path(arguments.get("path"))
        expected = str(arguments.get("expected", ""))
        if not path.is_file():
            return ToolResult(False, error="file_not_found", error_code="not_found")
        content = path.read_text(encoding="utf-8", errors="replace")
        matches = content == expected
        return ToolResult(
            matches, {"path": str(path), "matches": matches, "bytes": path.stat().st_size},
            error=None if matches else "file_content_mismatch",
            error_code=None if matches else "verification_failed",
            evidence={"file_exists": True, "exact_match": matches},
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("file_exists") and result.evidence.get("exact_match"))


class TerminalTool:
    manifest = TERMINAL_RUN_MANIFEST
    _CRITICAL = re.compile(
        r"(?i)(?:\bremove-item\b.*-recurse\b|\brm\s+-rf\b|\bformat(?:-volume)?\b|"
        r"\bshutdown\b|\bstop-computer\b|\bclear-disk\b|\bdelete\s+from\b|"
        r"\bnet\s+user\b|\bset-localuser\b|\breg\s+(?:delete|add)\b)"
    )

    def __init__(self, events: EventBus | None = None) -> None:
        self._lock = RLock()
        self._process: subprocess.Popen[str] | None = None
        self._events = events
        self._cancel = Event()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        if not command or len(command) > 16_384 or "\0" in command:
            return ToolResult(False, error="invalid_command", error_code="validation_failed")
        if self._CRITICAL.search(command):
            return ToolResult(
                False, error="critical_command_requires_dedicated_confirmed_tool",
                error_code="critical_action_blocked",
            )
        shell_name = str(arguments.get("shell", "powershell")).casefold()
        executable = "cmd.exe" if shell_name == "cmd" else "powershell.exe"
        argv = [executable, "/d", "/s", "/c", command] if shell_name == "cmd" else [
            executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command,
        ]
        cwd = _path(arguments.get("cwd", os.getcwd()))
        if not cwd.is_dir():
            return ToolResult(False, error="working_directory_not_found", error_code="not_found")
        timeout = max(0.5, min(float(arguments.get("timeout_seconds", 30.0)), 300.0))
        environment = os.environ.copy()
        raw_environment = arguments.get("environment", {})
        if not isinstance(raw_environment, Mapping):
            return ToolResult(False, error="environment_must_be_mapping", error_code="validation_failed")
        for key, value in raw_environment.items():
            name = str(key)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
                return ToolResult(False, error="invalid_environment_name", error_code="validation_failed")
            environment[name] = str(value)[:8192]
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        if self._cancel.is_set():
            self._cancel.clear()
            return ToolResult(
                False, {"cwd": str(cwd), "state": "cancelled"},
                error="command_cancelled", error_code="cancelled",
                evidence={"process_cleanup_verified": True},
            )
        with self._lock:
            self._process = subprocess.Popen(
                argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                creationflags=creation_flags, env=environment, bufsize=1,
            )
            process = self._process
        self._publish("terminal.started", {"cwd": str(cwd), "shell": shell_name}, context)
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def drain(stream: Any, destination: list[str], event: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    destination.append(line)
                    self._publish(event, {"chunk": line[-8192:]}, context, sensitive=True)
            finally:
                stream.close()

        readers = (
            Thread(target=drain, args=(process.stdout, stdout_parts, "terminal.output"), daemon=True),
            Thread(target=drain, args=(process.stderr, stderr_parts, "terminal.error"), daemon=True),
        )
        for reader in readers:
            reader.start()
        deadline = __import__("time").monotonic() + timeout
        state = "completed"
        try:
            try:
                while process.poll() is None:
                    if self._cancel.wait(0.05):
                        state = "cancelled"
                        self._terminate_tree(process)
                        break
                    if __import__("time").monotonic() >= deadline:
                        state = "timeout"
                        self._terminate_tree(process)
                        break
                process.wait(timeout=10)
                for reader in readers:
                    reader.join(timeout=2)
                stdout = "".join(stdout_parts)[-262144:]
                stderr = "".join(stderr_parts)[-262144:]
            except subprocess.TimeoutExpired:
                state = "timeout"
                self._terminate_tree(process)
                stdout = "".join(stdout_parts)[-262144:]
                stderr = "".join(stderr_parts)[-262144:]
            if state != "completed":
                self._publish(f"terminal.{state}", {"exit_code": process.returncode}, context)
                return ToolResult(
                    False, {"stdout": stdout, "stderr": stderr, "cwd": str(cwd), "state": state},
                    error=f"command_{state}", error_code=state,
                    evidence={"exit_code": process.returncode, "process_cleanup_verified": process.poll() is not None},
                )
            data = {
                "stdout": stdout[-262144:], "stderr": stderr[-262144:],
                "exit_code": int(process.returncode), "cwd": str(cwd), "shell": shell_name,
            }
            ok = process.returncode == 0
            self._publish("terminal.completed", {"exit_code": process.returncode}, context)
            return ToolResult(
                ok, data, error=None if ok else "command_failed",
                error_code=None if ok else "nonzero_exit",
                evidence={"exit_code": process.returncode, "process_cleanup_verified": process.poll() is not None},
            )
        finally:
            with self._lock:
                self._process = None
            self._cancel.clear()

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return result.data.get("exit_code") == 0

    def close(self) -> None:
        self.cancel()

    def cancel(self) -> bool:
        self._cancel.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._terminate_tree(self._process)
                return True
        return False

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        else:
            process.kill()

    def _publish(
        self, event: str, payload: Mapping[str, Any], context: ToolContext, *, sensitive: bool = False,
    ) -> None:
        if self._events is not None:
            self._events.publish(
                event, payload, source="terminal", correlation_id=context.correlation_id,
                sensitive=sensitive,
            )


class CancelTerminalTool:
    manifest = TERMINAL_CANCEL_MANIFEST

    def __init__(self, terminal: TerminalTool) -> None:
        self.terminal = terminal

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        cancelled = self.terminal.cancel()
        return ToolResult(
            True, {"cancel_requested": True, "active_process_found": cancelled},
            evidence={"cancel_signal_sent": True}, changed_state=cancelled,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("cancel_signal_sent"))


class AgentToolsEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine, events: EventBus | None = None) -> None:
        super().__init__("agent_tools")
        self._tools = tools
        self._terminal = TerminalTool(events)

    def _start(self) -> None:
        self._tools.register(FILE_LIST_MANIFEST, ListFolderTool)
        self._tools.register(FILE_SEARCH_MANIFEST, SearchFilesTool)
        self._tools.register(FILE_READ_MANIFEST, ReadTextFileTool)
        self._tools.register(FOLDER_CREATE_MANIFEST, CreateFolderTool)
        self._tools.register(FILE_ENSURE_MANIFEST, EnsureEmptyFileTool)
        self._tools.register(FILE_VERIFY_TEXT_MANIFEST, VerifyFileTextTool)
        self._tools.register(TERMINAL_RUN_MANIFEST, lambda: self._terminal)
        self._tools.register(TERMINAL_CANCEL_MANIFEST, lambda: CancelTerminalTool(self._terminal))

    def _stop(self) -> None:
        for manifest in (
            TERMINAL_CANCEL_MANIFEST, TERMINAL_RUN_MANIFEST, FILE_VERIFY_TEXT_MANIFEST, FILE_ENSURE_MANIFEST,
            FOLDER_CREATE_MANIFEST, FILE_READ_MANIFEST,
            FILE_SEARCH_MANIFEST, FILE_LIST_MANIFEST,
        ):
            self._tools.unregister(manifest.id)
