"""Repeatable lightweight resource/latency probe for Desktop Agent M2."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import psutil

from archeon.agent import AgentStep, AgentTask
from archeon.app import ArcheonApplication
from archeon.core.tools import ToolContext


ROOT = Path(__file__).resolve().parents[1]


def sample(process: psutil.Process) -> dict[str, float | int]:
    with process.oneshot():
        return {
            "rss_mb": round(process.memory_info().rss / 1024 / 1024, 3),
            "threads": process.num_threads(),
            "children": len(process.children(recursive=True)),
            "cpu_percent": process.cpu_percent(interval=0.25),
        }


def timed(action):
    started = time.perf_counter()
    value = action()
    return value, round((time.perf_counter() - started) * 1000, 3)


def main() -> int:
    process = psutil.Process()
    data_root = Path(tempfile.mkdtemp(prefix="archeon-m2-benchmark-"))
    application = ArcheonApplication(data_dir=data_root, port=0)
    before_children = {child.pid for child in process.children(recursive=True)}
    application.start()
    try:
        idle = sample(process)
        unloaded_tools = application.tools.loaded_tool_count
        desktop, desktop_ms = timed(lambda: application.tools.execute(
            "desktop.observe_active", {"visual_fingerprint": False},
            context=ToolContext("m2-bench-desktop", scope_permissions=frozenset({"desktop.observe"})),
        ))
        after_desktop = sample(process)
        terminal, terminal_ms = timed(lambda: application.tools.execute(
            "terminal.run", {"command": "Write-Output M2", "cwd": str(ROOT), "timeout_seconds": 10},
            context=ToolContext("m2-bench-terminal", scope_permissions=frozenset({"terminal.execute"})),
        ))
        document, document_ms = timed(lambda: application.tools.execute(
            "documents.read", {"path": str(ROOT / "tests" / "fixtures" / "document.pdf"), "page": 2},
            context=ToolContext("m2-bench-document", scope_permissions=frozenset({"filesystem.read"})),
        ))
        browser, browser_ms = timed(lambda: application.tools.execute(
            "browser.navigate", {"url": "https://docs.python.org/3/library/pathlib.html"},
            context=ToolContext("m2-bench-browser", scope_permissions=frozenset({"network.browser"})),
        ))
        task = AgentTask(
            "Verify a bounded multi-tool objective",
            (
                AgentStep("folder", "Read repository folder", "files.list", {"path": str(ROOT), "limit": 5}),
                AgentStep("document", "Read exact PDF page", "documents.read", {
                    "path": str(ROOT / "tests" / "fixtures" / "document.pdf"), "page": 2,
                }),
            ),
            ("folder and document verified",),
        )
        completed, task_ms = timed(lambda: application.agent_runner.run(
            task, scope_permissions=frozenset({"filesystem.read"}),
        ))
        verification_count = sum(1 for item in completed.tool_results if item["verified"])
        after_all = sample(process)
        time.sleep(0.4)
        residual_children = [
            child.pid for child in process.children(recursive=True)
            if child.pid not in before_children and child.is_running()
        ]
        report = {
            "milestone": "Desktop Agent M2",
            "vision": "audited_not_downloaded",
            "idle": idle,
            "desktop_agent_unloaded": {"loaded_tools": unloaded_tools, "rss_mb": idle["rss_mb"]},
            "operations": {
                "ui_automation": {"ok": desktop.ok, "verified": desktop.verified, "latency_ms": desktop_ms},
                "terminal": {"ok": terminal.ok, "latency_ms": terminal_ms, "process_cleanup": terminal.evidence.get("process_cleanup_verified")},
                "document_page_2": {"ok": document.ok, "latency_ms": document_ms},
                "browser_official_page": {"ok": browser.ok, "latency_ms": browser_ms},
                "agent_task": {
                    "status": completed.status.value, "latency_ms": task_ms,
                    "steps": len(completed.plan), "replans": 0,
                    "verification_rate": round(verification_count / max(1, len(completed.tool_results)), 3),
                },
            },
            "after_ui_automation": after_desktop,
            "after_all": after_all,
            "residual_child_processes": residual_children,
        }
        output = ROOT / "benchmarks" / "desktop-agent-m2.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if all((desktop.ok, terminal.ok, document.ok, browser.ok, not residual_children)) else 1
    finally:
        application.stop()


if __name__ == "__main__":
    raise SystemExit(main())
