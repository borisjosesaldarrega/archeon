"""Real controlled Files -> PDF -> Notepad -> verify multi-app milestone."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from archeon.agent import AgentMode, AgentStep, AgentTask, TaskContext
from archeon.app import ArcheonApplication


def main() -> int:
    fixture = Path(__file__).parents[1] / "tests" / "fixtures" / "document.pdf"
    with tempfile.TemporaryDirectory(prefix="archeon-m3-multiapp-") as temporary:
        root = Path(temporary)
        downloads = root / "Downloads"
        downloads.mkdir()
        source = downloads / "controlled-latest.pdf"
        shutil.copy2(fixture, source)
        output = downloads / "controlled-summary.txt"
        app = ArcheonApplication(data_dir=root / "app-data")
        app.start()
        started = time.perf_counter()
        task = AgentTask(
            "Find the latest controlled PDF and create a verified Notepad summary",
            (
                AgentStep("find", "Find latest PDF", "files.search",
                          {"path": str(downloads), "extension": "pdf", "recursive": False, "limit": 10}),
                AgentStep("summary", "Extract grounded title and summary", "documents.summarize",
                          {"path": {"$result": "find", "path": "results.0.path"}, "max_characters": 800}),
                AgentStep("create", "Create output", "files.ensure_empty", {"path": str(output)}),
                AgentStep("open", "Open Notepad", "desktop.launch_notepad", {"path": str(output)}),
                AgentStep("write", "Write composed cross-tool context", "desktop.type_text",
                          {"field_name": "Editor de texto", "expected_window_handle": {"$result": "open", "path": "window.handle"},
                           "text": {"$template": "Título: {title}\n\nResumen:\n{summary}", "$vars": {
                               "title": {"$result": "summary", "path": "title"},
                               "summary": {"$result": "summary", "path": "summary"},
                           }}}),
                AgentStep("menu", "Open File menu", "desktop.invoke", {"name": "Archivo"}),
                AgentStep("save", "Save", "desktop.invoke", {"name": "Guardar"}),
                AgentStep("verify", "Verify exact saved text", "files.verify_text",
                          {"path": str(output), "expected": {"$template": "Título: {title}\n\nResumen:\n{summary}", "$vars": {
                              "title": {"$result": "summary", "path": "title"},
                              "summary": {"$result": "summary", "path": "summary"},
                          }}}),
                AgentStep("close", "Close verified Notepad window", "desktop.close_window",
                          {"handle": {"$result": "open", "path": "window.handle"}, "timeout_seconds": 8}),
            ),
            ("PDF selected", "document parsed", "Notepad written", "file exact", "window closed"),
            AgentMode.CONTROL, context=TaskContext(active_folder=str(downloads)),
        )
        try:
            result = app.agent_runner.run(
                task, scope_permissions=frozenset({"filesystem.read", "filesystem.write",
                                                   "desktop.control", "desktop.close"}),
            )
            report = {"ok": result.status.value == "completed", "status": result.status.value,
                      "steps": len(result.plan), "verified_steps": result.current_step,
                      "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                      "retries": result.retries, "errors": result.errors,
                      "output_verified": any(item["step"] == "verify" and item["verified"] for item in result.tool_results),
                      "notepad_closed": any(item["step"] == "close" and item["verified"] for item in result.tool_results)}
        finally:
            app.stop()
        target = Path("benchmarks/desktop-agent-m3-multi-app.json")
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
