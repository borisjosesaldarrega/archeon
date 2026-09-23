from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archeon.agent import AgentRunner, AgentStep, AgentTask, TaskStatus, TaskStore
from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult


class SequencedTool:
    manifest = ToolManifest(id="test.sequence", description="Verified test action")

    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def execute(self, _context: ToolContext, arguments) -> ToolResult:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        return ToolResult(outcome, {"value": arguments.get("value"), "call": self.calls}, None if outcome else "retryable")

    def verify(self, _context: ToolContext, result: ToolResult) -> bool:
        return result.ok and bool(result.data.get("value"))


class AgentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        config = ConfigurationManager(Path(self.temp.name) / "config.json")
        config.start()
        self.events = EventBus()
        self.tools = ToolEngine(self.events, PermissionEngine(config))

    def tearDown(self) -> None:
        self.tools.stop()
        self.temp.cleanup()

    def test_retries_observes_verifies_and_continues_until_goal_complete(self) -> None:
        tool = SequencedTool([False, True, True])
        self.tools.register(tool.manifest, lambda: tool)
        self.tools.start()
        task = AgentTask(
            goal="Complete both verified actions",
            plan=(
                AgentStep("inspect", "Inspect", "test.sequence", {"value": "observed"}, max_retries=1),
                AgentStep("verify", "Verify", "test.sequence", {"value": "complete"}),
            ),
            completion_criteria=("both tool results verified",),
        )
        result = AgentRunner(self.events, self.tools).run(task)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(result.current_step, 2)
        self.assertEqual(result.retries, {"inspect": 1})
        self.assertEqual(len(result.observations), 3)
        self.assertEqual(len(result.tool_results), 3)
        self.assertEqual(tool.calls, 3)

    def test_unknown_tool_is_rejected_before_execution(self) -> None:
        self.tools.start()
        task = AgentTask("Unsafe direct action", (AgentStep("bad", "Bad", "shell.direct"),), ("never",))
        result = AgentRunner(self.events, self.tools).run(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("unknown tool", result.errors[0])

    def test_failed_subtask_can_be_recorded_while_safe_remaining_steps_continue(self) -> None:
        tool = SequencedTool([False, True])
        self.tools.register(tool.manifest, lambda: tool)
        self.tools.start()
        task = AgentTask(
            "Continue independent work after one failure",
            (
                AgentStep("optional", "Optional output", "test.sequence", {"value": "first"}, max_retries=0, continue_on_failure=True),
                AgentStep("remaining", "Safe remaining output", "test.sequence", {"value": "second"}, max_retries=0),
            ),
            ("record exact failure", "complete safe remaining task"),
        )
        result = AgentRunner(self.events, self.tools).run(task)
        self.assertEqual(result.status, TaskStatus.PARTIAL)
        self.assertEqual(result.current_step, 2)
        self.assertEqual(tool.calls, 2)
        self.assertIn("optional: retryable", result.errors)

    def test_cancellation_is_terminal(self) -> None:
        task = AgentTask("Cancelled", (), ("none",))
        task.cancel()
        result = AgentRunner(self.events, self.tools).run(task)
        self.assertEqual(result.status, TaskStatus.CANCELLED)

    def test_task_state_persists_locally_and_resumes(self) -> None:
        store = TaskStore(Path(self.temp.name) / "memory" / "tasks")
        task = AgentTask(
            "Repair project",
            (AgentStep("inspect", "Inspect project", "system.status"),),
            ("verified inspection",),
        )
        task.observations.append({"kind": "checkpoint", "value": "clean"})
        path = store.save(task)
        restored = store.load(task.id)
        self.assertTrue(path.is_relative_to(Path(self.temp.name)))
        self.assertIsNotNone(restored)
        self.assertEqual(restored.goal, task.goal)
        self.assertEqual(restored.observations, task.observations)
        self.assertEqual(restored.status, TaskStatus.PLANNED)

    def test_task_store_redacts_visual_and_terminal_bodies(self) -> None:
        import json

        store = TaskStore(Path(self.temp.name) / "memory" / "tasks")
        task = AgentTask("Inspect private window", (), ("observed",))
        task.observations.append({"window_summary": "private title", "visible_text": ["secret"],
                                  "controls": [{"name": "password"}], "regions": [{"bounds": [0, 0, 1, 1]}],
                                  "errors": ["private error"], "stdout": "token"})
        path = store.save(task)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        body = json.dumps(persisted)
        self.assertNotIn("private title", body)
        self.assertNotIn("secret", body)
        self.assertNotIn("password", body)
        self.assertNotIn("private error", body)
        self.assertNotIn("token", body)
        self.assertIn("errors_redacted", body)

    def test_verified_tool_results_advance_multi_app_context(self) -> None:
        class WindowTool:
            manifest = ToolManifest(id="desktop.test_window", description="Context window")

            def execute(self, _context, _arguments):
                return ToolResult(True, {"window": {
                    "handle": 42, "title": "Document", "process_name": "Editor.exe",
                }})

            def verify(self, _context, _result):
                return True

        tool = WindowTool()
        self.tools.register(tool.manifest, lambda: tool)
        self.tools.start()
        task = AgentTask(
            "Remember target application",
            (AgentStep("window", "Switch application", tool.manifest.id),),
            ("context grounded",),
        )
        result = AgentRunner(self.events, self.tools).run(task)
        self.assertEqual(result.context.active_app, "Editor.exe")
        self.assertEqual(result.context.active_window, "Document")
        self.assertEqual(result.context.target_window["handle"], 42)

    def test_result_templates_carry_grounded_context_between_apps(self) -> None:
        task = AgentTask("Compose across tools", (), ("composed",))
        task.tool_results.append({"step": "read-pdf", "data": {"metadata": {"title": "ARCHEON Report"}}})
        resolved = AgentRunner._resolve_arguments(task, {
            "$template": "Título: {title}\nResumen verificado.",
            "$vars": {"title": {"$result": "read-pdf", "path": "metadata.title"}},
        })
        self.assertEqual(resolved, "Título: ARCHEON Report\nResumen verificado.")

    def test_verified_result_is_exposed_to_visual_evidence_observer(self) -> None:
        tool = SequencedTool([True])
        self.tools.register(tool.manifest, lambda: tool)
        self.tools.start()
        observed = []
        task = AgentTask("Show evidence", (AgentStep("visible", "Visible action", tool.manifest.id, {"value": "ok"}),), ("visible",))
        result = AgentRunner(
            self.events, self.tools,
            result_observer=lambda current, step, tool_result: observed.append((current.id, step.id, tool_result.data["value"])),
        ).run(task)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(observed, [(task.id, "visible", "ok")])

    def test_tool_exception_reports_component_operation_and_target(self) -> None:
        class BrokenFileTool:
            manifest = ToolManifest(id="test.broken_file", description="Broken file")
            def execute(self, _context, _arguments): raise OSError("access denied")
            def verify(self, _context, _result): return False

        tool = BrokenFileTool()
        self.tools.register(tool.manifest, lambda: tool)
        self.tools.start()
        result = self.tools.execute(tool.manifest.id, {"path": "C:/example/output.docx"})
        self.assertFalse(result.ok)
        self.assertEqual(result.data["component"], tool.manifest.id)
        self.assertEqual(result.data["operation"], "execute")
        self.assertEqual(result.data["target"], "C:/example/output.docx")
        self.assertIn("access denied", result.error)

    def test_replanner_replaces_failed_step_and_completes_without_looping(self) -> None:
        failed = SequencedTool([False])
        recovered = SequencedTool([True])
        failed.manifest = ToolManifest(id="test.stale", description="Stale target")
        recovered.manifest = ToolManifest(id="test.recovered", description="Recovered target")
        self.tools.register(failed.manifest, lambda: failed)
        self.tools.register(recovered.manifest, lambda: recovered)
        self.tools.start()
        task = AgentTask("Recover moved target", (AgentStep("stale", "Old target", "test.stale", {"value": "x"}, max_retries=0),), ("recovered",))

        def replan(_task, _step, _result):
            return (AgentStep("reobserve-and-retry", "Recovered target", "test.recovered", {"value": "fresh"}, max_retries=0),)

        result = AgentRunner(self.events, self.tools, replanner=replan, max_actions=4).run(task)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(result.replans, 1)
        self.assertEqual(len(result.actions), 2)


if __name__ == "__main__":
    unittest.main()
