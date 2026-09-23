from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine
from archeon.programming import ProgrammingAgentEngine, ProjectDetector
from archeon.programming.operations import git_status, repair_python_project, search_code


class ProgrammingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname='controlled-fixture'\nversion='0.0.1'\n", encoding="utf-8")
        (self.root / "app.py").write_text(
            'def message():\n    return "ARCHI FIXED"\n\nprint(mesage())\n', encoding="utf-8",
        )
        self.config = ConfigurationManager(Path(self.temp.name) / "config.json")
        self.config.start()
        self.events = EventBus()
        self.tools = ToolEngine(self.events, PermissionEngine(self.config))
        self.agent = ProgrammingAgentEngine(self.tools)
        self.agent.start(); self.tools.start()

    def tearDown(self) -> None:
        self.tools.stop(); self.agent.stop(); self.events.close(); self.config.stop(); self.temp.cleanup()

    @staticmethod
    def context(*permissions: str) -> ToolContext:
        return ToolContext("programming-test", scope_permissions=frozenset(permissions))

    def test_project_detection_and_bounded_code_search(self) -> None:
        project = ProjectDetector().detect(self.root)
        found = search_code(self.root, "mesage")
        self.assertIn("python", project.kinds)
        self.assertEqual(project.entrypoints, ("app.py",))
        self.assertEqual(project.suggested_command[0], sys.executable)
        self.assertEqual(found["matches"][0]["path"], "app.py")
        self.assertEqual(found["matches"][0]["line"], 4)

    def test_tools_reproduce_checkpoint_patch_and_verify_startup(self) -> None:
        detect = self.tools.execute(
            "programming.detect", {"path": str(self.root)}, context=self.context("filesystem.read"),
        )
        diagnosis = self.tools.execute(
            "programming.diagnose_startup", {
                "root": str(self.root), "command": detect.data["suggested_command"],
            }, context=self.context("filesystem.read", "terminal.execute"),
        )
        patched = self.tools.execute(
            "programming.apply_diagnostic_fix", {
                "root": str(self.root), "relative_file": diagnosis.data["relative_file"],
                "line": diagnosis.data["line"], "undefined_name": diagnosis.data["undefined_name"],
                "suggested_name": diagnosis.data["suggested_name"],
            }, context=self.context("filesystem.read", "filesystem.write"),
        )
        verified = self.tools.execute(
            "programming.verify_startup", {
                "root": str(self.root), "command": detect.data["suggested_command"],
            }, context=self.context("filesystem.read", "terminal.execute"),
        )
        self.assertTrue(detect.verified)
        self.assertTrue(diagnosis.verified)
        self.assertEqual(diagnosis.data["error_type"], "NameError")
        self.assertEqual(diagnosis.data["suggested_name"], "message")
        self.assertTrue(patched.verified)
        self.assertTrue(Path(patched.data["checkpoint"]).is_file())
        self.assertTrue(verified.verified)
        self.assertEqual(verified.data["stdout"].strip(), "ARCHI FIXED")
        self.assertTrue(verified.data["process_cleanup_verified"])

    def test_git_status_is_read_only_and_reports_user_change(self) -> None:
        git = subprocess.run(["git", "--version"], capture_output=True, check=False)
        if git.returncode != 0:
            self.skipTest("git unavailable")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "user-notes.txt").write_text("do not overwrite", encoding="utf-8")
        before = (self.root / "user-notes.txt").read_bytes()
        status = git_status(self.root)
        after = (self.root / "user-notes.txt").read_bytes()
        self.assertTrue(status["git"] and status["dirty"])
        self.assertEqual(before, after)
        self.assertTrue(any(item["path"] == "user-notes.txt" for item in status["changes"]))

    def test_m3_repair_loop_fixes_syntax_then_logic_and_verifies_startup(self) -> None:
        (self.root / "app.py").write_text(
            "def double(value)\n    return value + 1\n\nif __name__ == '__main__':\n    print(double(2))\n",
            encoding="utf-8",
        )
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text(
            "from app import double\n\n"
            "def test_double_contract():\n"
            "    assert double(2) == 4\n"
            "    assert double(3) == 6\n",
            encoding="utf-8",
        )
        project = ProjectDetector().detect(self.root)
        self.assertEqual(project.test_framework, "pytest")
        self.assertEqual(project.build_system, "pyproject")
        result = repair_python_project(self.root, max_iterations=6, timeout_seconds=20)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(result["tests_verified"] and result["startup_verified"])
        self.assertEqual([item["fix"] for item in result["patches"]],
                         ["missing_colon", "inferred_linear_contract"])
        self.assertGreaterEqual(result["replans"], 2)
        self.assertTrue(all(Path(item["checkpoint"]).is_file() for item in result["patches"]))
        self.assertIn("return value * 2", (self.root / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
