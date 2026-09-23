"""Git inspection, bounded execution, search, diagnostics and checkpointed patching."""

from __future__ import annotations

import difflib
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


def confined(root: str | Path, value: str | Path) -> Path:
    project = Path(root).expanduser().resolve()
    target = Path(value)
    if not target.is_absolute():
        target = project / target
    target = target.resolve()
    if target != project and project not in target.parents:
        raise ValueError("path_outside_project")
    return target


def git_status(root: str | Path) -> dict[str, Any]:
    project = Path(root).resolve()
    git = shutil.which("git")
    if not git or not (project / ".git").exists():
        return {"root": str(project), "git": False, "dirty": False, "changes": []}
    completed = subprocess.run(
        [git, "-C", str(project), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git_status_failed")
    entries = completed.stdout.decode("utf-8", "replace").split("\0")
    changes = []
    for entry in entries:
        if len(entry) >= 4:
            changes.append({"status": entry[:2], "path": entry[3:]})
    return {"root": str(project), "git": True, "dirty": bool(changes), "changes": changes[:500]}


def run_bounded(root: str | Path, command: Sequence[str], *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    project = Path(root).resolve()
    argv = [str(item) for item in command]
    if not argv or len(argv) > 32 or any(not item or "\0" in item for item in argv):
        raise ValueError("invalid_program_command")
    executable = shutil.which(argv[0]) or (argv[0] if Path(argv[0]).is_file() else None)
    if not executable:
        raise FileNotFoundError("program_executable_not_found")
    argv[0] = executable
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    started = time.perf_counter()
    process = subprocess.Popen(
        argv, cwd=str(project), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=flags,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=max(0.5, min(timeout_seconds, 300.0)))
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        else:
            process.kill()
        stdout, stderr = process.communicate()
    return {
        "command": argv, "cwd": str(project), "exit_code": int(process.returncode),
        "stdout": stdout[-262_144:].decode("utf-8", "replace"),
        "stderr": stderr[-262_144:].decode("utf-8", "replace"),
        "timed_out": timed_out,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "process_cleanup_verified": process.poll() is not None,
    }


def diagnose_python_failure(root: str | Path, command: Sequence[str], *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    result = run_bounded(root, command, timeout_seconds=timeout_seconds)
    stderr = result["stderr"]
    frames = re.findall(r'File "([^"]+)", line (\d+)', stderr)
    error = re.search(r"(?m)^([A-Za-z]+Error):\s*(.+)$", stderr)
    undefined = re.search(r"name '([^']+)' is not defined", stderr)
    suggestion = re.search(r"Did you mean:\s*'([^']+)'", stderr)
    relative_file = ""
    line = 0
    if frames:
        raw_file, raw_line = frames[-1]
        file_path = confined(root, raw_file)
        relative_file = str(file_path.relative_to(Path(root).resolve()))
        line = int(raw_line)
    return {
        **result, "failure_reproduced": result["exit_code"] != 0 and not result["timed_out"],
        "error_type": error.group(1) if error else "",
        "error_message": error.group(2)[:500] if error else "",
        "relative_file": relative_file, "line": line,
        "undefined_name": undefined.group(1) if undefined else "",
        "suggested_name": suggestion.group(1) if suggestion else "",
    }


def search_code(root: str | Path, query: str, *, regex: bool = False, limit: int = 100) -> dict[str, Any]:
    project = Path(root).resolve()
    if not query or len(query) > 500:
        raise ValueError("invalid_code_query")
    pattern = re.compile(query if regex else re.escape(query))
    matches: list[dict[str, Any]] = []
    visited = 0
    ignored = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
    for path in project.rglob("*"):
        if any(part in ignored for part in path.relative_to(project).parts):
            continue
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        visited += 1
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
                if pattern.search(line):
                    matches.append({"path": str(path.relative_to(project)), "line": line_number, "text": line[:500]})
                    if len(matches) >= max(1, min(limit, 500)):
                        return {"root": str(project), "query": query, "matches": matches, "visited": visited, "truncated": True}
        except (OSError, UnicodeError):
            continue
        if visited >= 5000:
            break
    return {"root": str(project), "query": query, "matches": matches, "visited": visited, "truncated": visited >= 5000}


def apply_name_error_fix(
    root: str | Path, relative_file: str, line: int, undefined_name: str, suggested_name: str,
) -> dict[str, Any]:
    project = Path(root).resolve()
    target = confined(project, relative_file)
    if not target.is_file() or target.stat().st_size > 4_000_000:
        raise ValueError("patch_target_invalid")
    if not re.fullmatch(r"[A-Za-z_]\w*", undefined_name) or not re.fullmatch(r"[A-Za-z_]\w*", suggested_name):
        raise ValueError("diagnostic_fix_not_unambiguous")
    original = target.read_text(encoding="utf-8", errors="strict")
    lines = original.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        raise IndexError("diagnostic_line_out_of_range")
    token = re.compile(rf"\b{re.escape(undefined_name)}\b")
    if len(token.findall(lines[line - 1])) != 1:
        raise ValueError("diagnostic_token_not_unique_on_line")
    lines[line - 1] = token.sub(suggested_name, lines[line - 1], count=1)
    changed = "".join(lines)
    checkpoint_root = project / ".archeon" / "checkpoints" / str(time.time_ns())
    checkpoint = checkpoint_root / target.relative_to(project)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, checkpoint)
    temporary = target.with_suffix(target.suffix + ".archeon-tmp")
    temporary.write_text(changed, encoding="utf-8")
    temporary.replace(target)
    reopened = target.read_text(encoding="utf-8", errors="strict")
    if reopened != changed:
        shutil.copy2(checkpoint, target)
        raise RuntimeError("patch_reopen_verification_failed")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), changed.splitlines(keepends=True),
        fromfile=f"a/{relative_file}", tofile=f"b/{relative_file}", n=3,
    ))
    return {
        "root": str(project), "path": str(target), "relative_file": relative_file,
        "line": line, "checkpoint": str(checkpoint), "diff": diff[:100_000],
        "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(changed.encode()).hexdigest(),
        "reopened": True, "changed_state": original != changed,
    }


def structured_transcript(results: Sequence[dict[str, Any]]) -> str:
    safe = []
    for item in results:
        safe.append({key: value for key, value in item.items() if key not in {"stdout", "stderr", "diff"}})
    return json.dumps(safe, ensure_ascii=False, indent=2)


def _invalidate_source_bytecode(project: Path, target: Path) -> None:
    """Remove only generated bytecode for a source file after atomic repair.

    Two same-size edits inside one filesystem timestamp tick can otherwise make
    a new Python subprocess reuse stale bytecode and request the same patch.
    """
    cache = target.parent / "__pycache__"
    if not cache.is_dir() or (cache != project and project not in cache.resolve().parents): return
    for compiled in cache.glob(f"{target.stem}.*.pyc"):
        try: compiled.unlink()
        except OSError: pass


def _checkpointed_replace(project: Path, target: Path, original: str, changed: str) -> dict[str, Any]:
    if original == changed:
        raise ValueError("patch_did_not_change_source")
    checkpoint_root = project / ".archeon" / "checkpoints" / str(time.time_ns())
    checkpoint = checkpoint_root / target.relative_to(project)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, checkpoint)
    temporary = target.with_suffix(target.suffix + ".archeon-tmp")
    temporary.write_text(changed, encoding="utf-8")
    temporary.replace(target)
    _invalidate_source_bytecode(project, target)
    try:
        ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    except SyntaxError:
        shutil.copy2(checkpoint, target)
        raise
    return {
        "path": str(target), "checkpoint": str(checkpoint),
        "diff": "".join(difflib.unified_diff(
            original.splitlines(keepends=True), changed.splitlines(keepends=True),
            fromfile=f"a/{target.relative_to(project)}", tofile=f"b/{target.relative_to(project)}", n=3,
        ))[:100_000],
    }


def _fix_missing_colon(project: Path, stderr: str) -> dict[str, Any] | None:
    match = re.search(r'File "([^"]+)", line (\d+).*?SyntaxError:\s*expected [\'\"]?:[\'\"]?', stderr, re.DOTALL)
    if not match:
        return None
    target = confined(project, match.group(1))
    line_number = int(match.group(2))
    original = target.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    if line_number < 1 or line_number > len(lines):
        return None
    raw = lines[line_number - 1]
    ending = "\n" if raw.endswith("\n") else ""
    body = raw.rstrip("\r\n")
    if body.rstrip().endswith(":") or not re.match(r"\s*(?:def|async\s+def|class|if|elif|else|for|while|try|except|finally|with|match|case)\b", body):
        return None
    lines[line_number - 1] = body.rstrip() + ":" + ending
    data = _checkpointed_replace(project, target, original, "".join(lines))
    return {**data, "fix": "missing_colon", "line": line_number}


def _python_files(project: Path) -> list[Path]:
    ignored = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".archeon"}
    return [path for path in project.rglob("*.py") if not any(part in ignored for part in path.relative_to(project).parts)]


def _infer_linear_function_fix(project: Path) -> dict[str, Any] | None:
    examples: dict[str, list[tuple[int | float, int | float]]] = {}
    for path in _python_files(project):
        if "test" not in path.name.casefold() and "tests" not in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1:
                continue
            if not isinstance(node.test.ops[0], ast.Eq) or len(node.test.comparators) != 1:
                continue
            call, expected = node.test.left, node.test.comparators[0]
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or len(call.args) != 1:
                continue
            if not isinstance(call.args[0], ast.Constant) or not isinstance(expected, ast.Constant):
                continue
            x, y = call.args[0].value, expected.value
            if isinstance(x, (int, float)) and not isinstance(x, bool) and isinstance(y, (int, float)) and not isinstance(y, bool):
                examples.setdefault(call.func.id, []).append((x, y))
    candidates = [(name, pairs) for name, pairs in examples.items() if len(set(pairs)) >= 2]
    if len(candidates) != 1:
        return None
    name, pairs = candidates[0]
    (x1, y1), (x2, y2) = pairs[:2]
    if x1 == x2:
        return None
    slope = (y2 - y1) / (x2 - x1)
    intercept = y1 - slope * x1
    if any(abs((slope * x + intercept) - y) > 1e-9 for x, y in pairs):
        return None
    if not float(slope).is_integer() or not float(intercept).is_integer() or abs(slope) > 100 or abs(intercept) > 1000:
        return None
    for target in _python_files(project):
        if "test" in target.name.casefold() or "tests" in target.parts:
            continue
        try:
            original = target.read_text(encoding="utf-8")
            tree = ast.parse(original, filename=str(target))
        except (OSError, SyntaxError, UnicodeError):
            continue
        matches = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
        if len(matches) != 1 or len(matches[0].args.args) != 1 or len(matches[0].body) != 1 or not isinstance(matches[0].body[0], ast.Return):
            continue
        function, returned = matches[0], matches[0].body[0]
        argument = function.args.args[0].arg
        a, b = int(slope), int(intercept)
        expression = argument if a == 1 else f"{argument} * {a}"
        if b:
            expression += f" {'+' if b > 0 else '-'} {abs(b)}"
        lines = original.splitlines(keepends=True)
        source_line = lines[returned.lineno - 1]
        indent = source_line[:len(source_line) - len(source_line.lstrip())]
        ending = "\n" if source_line.endswith("\n") else ""
        lines[returned.lineno - 1] = f"{indent}return {expression}{ending}"
        data = _checkpointed_replace(project, target, original, "".join(lines))
        return {**data, "fix": "inferred_linear_contract", "function": name,
                "examples": [[x, y] for x, y in pairs], "expression": expression}
    return None


def repair_python_project(root: str | Path, *, max_iterations: int = 8, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Bounded error-first repair for explicit, locally verifiable Python failures."""
    project = Path(root).expanduser().resolve()
    info = __import__("archeon.programming.project", fromlist=["ProjectDetector"]).ProjectDetector().detect(project)
    command: tuple[str, ...]
    if info.test_framework == "pytest":
        command = (sys.executable, "-m", "pytest", "-q")
    else:
        command = info.suggested_command
    if not command:
        raise ValueError("project_command_not_detected")
    before_git = git_status(project)
    iterations: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []
    replans = 0
    for index in range(max(1, min(max_iterations, 16))):
        result = run_bounded(project, command, timeout_seconds=timeout_seconds)
        iterations.append({"iteration": index + 1, "exit_code": result["exit_code"],
                           "duration_ms": result["duration_ms"], "timed_out": result["timed_out"],
                           "stderr_tail": result["stderr"][-4000:], "stdout_tail": result["stdout"][-4000:]})
        if result["exit_code"] == 0 and not result["timed_out"]:
            startup = None
            if info.suggested_command and tuple(info.suggested_command) != command:
                startup = run_bounded(project, info.suggested_command, timeout_seconds=timeout_seconds)
                if startup["exit_code"] != 0 or startup["timed_out"]:
                    iterations.append({"iteration": index + 1, "phase": "startup", "exit_code": startup["exit_code"],
                                       "stderr_tail": startup["stderr"][-4000:]})
                    result = startup
                else:
                    return {"root": str(project), "status": "completed", "command": list(command),
                            "iterations": iterations, "patches": patches, "replans": replans,
                            "git_before": before_git, "git_after": git_status(project),
                            "tests_verified": True, "startup_verified": True,
                            "process_cleanup_verified": all(item.get("timed_out") is not True for item in iterations)}
            else:
                return {"root": str(project), "status": "completed", "command": list(command),
                        "iterations": iterations, "patches": patches, "replans": replans,
                        "git_before": before_git, "git_after": git_status(project),
                        "tests_verified": True, "startup_verified": startup is None,
                        "process_cleanup_verified": True}
        combined_output = result["stdout"] + "\n" + result["stderr"]
        patch = _fix_missing_colon(project, combined_output)
        if patch is None:
            diagnosis = diagnose_python_failure(project, command, timeout_seconds=timeout_seconds)
            if not diagnosis.get("error_type") and combined_output:
                error = re.search(r"(?m)^E?\s*([A-Za-z]+Error):\s*(.+)$", combined_output)
                undefined = re.search(r"name '([^']+)' is not defined", combined_output)
                suggestion = re.search(r"Did you mean:\s*'([^']+)'", combined_output)
                frames = re.findall(r'File "([^"]+)", line (\d+)', combined_output)
                if error:
                    diagnosis["error_type"], diagnosis["error_message"] = error.group(1), error.group(2)[:500]
                if undefined:
                    diagnosis["undefined_name"] = undefined.group(1)
                if suggestion:
                    diagnosis["suggested_name"] = suggestion.group(1)
                if frames:
                    target, line = frames[-1]
                    diagnosis["relative_file"] = str(confined(project, target).relative_to(project))
                    diagnosis["line"] = int(line)
            if diagnosis.get("undefined_name") and diagnosis.get("suggested_name"):
                patch = apply_name_error_fix(project, diagnosis["relative_file"], diagnosis["line"],
                                             diagnosis["undefined_name"], diagnosis["suggested_name"])
                patch["fix"] = "diagnostic_name_error"
            else:
                patch = _infer_linear_function_fix(project)
        if patch is None:
            return {"root": str(project), "status": "blocked", "command": list(command),
                    "iterations": iterations, "patches": patches, "replans": replans,
                    "git_before": before_git, "git_after": git_status(project),
                    "error": "no_unambiguous_verified_patch", "tests_verified": False,
                    "startup_verified": False, "process_cleanup_verified": True}
        patches.append(patch)
        replans += 1
    return {"root": str(project), "status": "blocked", "command": list(command),
            "iterations": iterations, "patches": patches, "replans": replans,
            "git_before": before_git, "git_after": git_status(project),
            "error": "repair_iteration_limit", "tests_verified": False,
            "startup_verified": False, "process_cleanup_verified": True}
