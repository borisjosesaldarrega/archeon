from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from threading import Thread

from archeon.agent import AgentMode, AgentRunner, AgentStep, AgentTask, AgentToolsEngine, TaskContext, TaskStatus, TaskStore
from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine
from archeon.desktop import DesktopAgentEngine, WindowsDesktopObserver
from archeon.desktop.mouse import normalize_virtual_point


class DesktopAgentFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigurationManager(self.root / "config.json")
        self.config.start()
        self.events = EventBus()
        self.tools = ToolEngine(self.events, PermissionEngine(self.config))
        self.desktop = DesktopAgentEngine(self.tools)
        self.agent_tools = AgentToolsEngine(self.tools, self.events)
        self.desktop.start()
        self.agent_tools.start()
        self.tools.start()

    def tearDown(self) -> None:
        self.tools.stop()
        self.agent_tools.stop()
        self.desktop.stop()
        self.events.close()
        self.config.stop()
        self.temp.cleanup()

    def context(self, *permissions: str) -> ToolContext:
        return ToolContext("test-task", scope_permissions=frozenset(permissions))

    def test_task_schema_contains_mode_context_actions_and_requested_states(self) -> None:
        task = AgentTask("Observe", (), ("verified",), mode=AgentMode.OBSERVE)
        task.context = TaskContext(
            active_window="Example", previous_window="Previous", target_window="Target",
            recent_download="download.pdf", current_url="https://example.test", current_tab="Docs",
            current_goal=task.goal,
        )
        public = task.public()
        self.assertEqual(public["mode"], "observe")
        self.assertEqual(public["status"], TaskStatus.PLANNING.value)
        self.assertEqual(public["actions"], [])
        self.assertEqual(public["context"]["active_window"], "Example")
        self.assertEqual(public["context"]["target_window"], "Target")
        self.assertEqual(public["context"]["current_tab"], "Docs")
        self.assertIn(TaskStatus.OBSERVING, TaskStatus)
        self.assertIn(TaskStatus.VERIFYING, TaskStatus)

    def test_task_scoped_permission_does_not_become_session_grant(self) -> None:
        allowed = self.tools.execute(
            "files.list", {"path": str(self.root)}, context=self.context("filesystem.read"),
        )
        denied_after = self.tools.execute("files.list", {"path": str(self.root)})
        self.assertTrue(allowed.ok and allowed.verified)
        self.assertFalse(denied_after.ok)

    def test_task_store_does_not_persist_screen_or_terminal_bodies(self) -> None:
        task = AgentTask("Inspect", (), ("verified",))
        task.tool_results.append({
            "tool_id": "desktop.observe_active",
            "data": {"elements": [{"name": "private screen text"}], "content": "private document"},
            "stdout": "private terminal output",
            "clipboard_text": "private clipboard text",
        })
        store = TaskStore(self.root / "tasks")
        text = store.save(task).read_text(encoding="utf-8")
        self.assertNotIn("private screen text", text)
        self.assertNotIn("private document", text)
        self.assertNotIn("private terminal output", text)
        self.assertNotIn("private clipboard text", text)
        self.assertIn("elements_redacted", text)

    def test_runner_resolves_verified_result_and_context_into_next_step(self) -> None:
        task = AgentTask(
            "Resolve chained evidence",
            (
                AgentStep("locate", "List the fixture", "files.list", {"path": str(self.root)}),
                AgentStep(
                    "read", "List the resolved fixture", "files.list",
                    {"path": {"$result": "locate", "path": "path"}, "limit": 1},
                ),
            ),
            ("both steps verified",), context=TaskContext(current_goal="Resolve chained evidence"),
        )
        result = AgentRunner(self.events, self.tools).run(
            task, scope_permissions=frozenset({"filesystem.read"}),
        )
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(result.current_step, 2)
        self.assertEqual(result.tool_results[0]["data"]["path"], str(self.root.resolve()))

    def test_virtual_screen_coordinates_support_negative_origin_and_edges(self) -> None:
        virtual = (-1920, -200, 4480, 1640)
        self.assertEqual(normalize_virtual_point(-1920, -200, virtual), (0, 0))
        self.assertEqual(normalize_virtual_point(2559, 1439, virtual), (65535, 65535))
        center = normalize_virtual_point(320, 620, virtual)
        self.assertTrue(32750 <= center[0] <= 32785)
        self.assertTrue(32750 <= center[1] <= 32800)

    def test_file_create_search_and_read_are_verified(self) -> None:
        folder = self.root / "Downloads" / "Prueba"
        created = self.tools.execute(
            "files.create_folder", {"path": str(folder), "parents": True},
            context=self.context("filesystem.write"),
        )
        (folder / "archi-test.txt").write_text("Prueba de ARCHI", encoding="utf-8")
        found = self.tools.execute(
            "files.search", {"path": str(folder.parent), "query": "archi-test", "extension": "txt"},
            context=self.context("filesystem.read"),
        )
        read = self.tools.execute(
            "files.read", {"path": str(folder / "archi-test.txt")},
            context=self.context("filesystem.read"),
        )
        self.assertTrue(created.verified)
        self.assertTrue(found.verified)
        self.assertEqual(found.data["results"][0]["name"], "archi-test.txt")
        self.assertTrue(read.verified)
        self.assertEqual(read.data["content"], "Prueba de ARCHI")

    def test_terminal_has_exit_evidence_and_blocks_critical_command(self) -> None:
        safe = self.tools.execute(
            "terminal.run", {"command": "Write-Output ARCHI", "cwd": str(self.root)},
            context=self.context("terminal.execute"),
        )
        blocked = self.tools.execute(
            "terminal.run", {"command": "Remove-Item C:\\example -Recurse", "cwd": str(self.root)},
            context=self.context("terminal.execute"),
        )
        self.assertTrue(safe.ok and safe.verified)
        self.assertIn("ARCHI", safe.data["stdout"])
        self.assertEqual(safe.evidence["exit_code"], 0)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error_code, "critical_action_blocked")

    def test_terminal_streams_sensitive_events_and_cancels_process_tree(self) -> None:
        subscription = self.events.subscribe("terminal.*", max_queue=20)
        completed: Queue = Queue()

        def run() -> None:
            completed.put(self.tools.execute(
                "terminal.run", {
                    "command": "Write-Output first; Start-Sleep -Seconds 10; Write-Output second",
                    "cwd": str(self.root), "timeout_seconds": 20,
                }, context=self.context("terminal.execute"),
            ))

        worker = Thread(target=run)
        worker.start()
        observed_output = False
        for _ in range(10):
            event = subscription.get(timeout=2)
            if event.type == "terminal.output":
                observed_output = True
                self.assertTrue(event.sensitive)
                break
        cancelled = self.tools.execute(
            "terminal.cancel", {}, context=self.context("terminal.execute"),
        )
        worker.join(timeout=10)
        result = completed.get(timeout=1)
        subscription.close()
        self.assertTrue(observed_output)
        self.assertTrue(cancelled.ok and cancelled.verified)
        self.assertEqual(result.error_code, "cancelled")
        self.assertTrue(result.evidence["process_cleanup_verified"])
        self.assertFalse(worker.is_alive())

    @unittest.skipUnless(sys.platform == "win32", "Windows-only observation")
    def test_real_active_window_observation_has_verified_evidence(self) -> None:
        import ctypes

        if not int(ctypes.windll.user32.GetForegroundWindow()):
            self.skipTest("Windows session has no foreground window in this test context")
        command = (
            "import json; from archeon.desktop import WindowsDesktopObserver; "
            "print(json.dumps(WindowsDesktopObserver(max_elements=20).observe_active()))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", command], check=True, capture_output=True, text=True,
        )
        import json

        evidence = json.loads(completed.stdout)
        self.assertGreater(evidence["window"]["handle"], 0)
        self.assertGreater(evidence["window"]["process_id"], 0)
        self.assertEqual(len(evidence["state_hash"]), 64)
        if "visual" in evidence:
            self.assertFalse(evidence["visual"].get("persisted", True))


if __name__ == "__main__":
    unittest.main()
