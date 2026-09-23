"""Permission-gated Project/Git/Search/Diagnostics/Patch/Verification tools."""

from __future__ import annotations

from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .operations import (
    apply_name_error_fix, diagnose_python_failure, git_status, repair_python_project,
    run_bounded, search_code,
)
from .project import ProjectDetector
from .planning import ProjectCompletionGate, ProjectPlanner
from .languages import ProgrammingLanguageRouter, ProjectTypeResolver, ToolchainDetector


DETECT = ToolManifest("programming.detect", "Detect project type and entrypoint from local markers", ("filesystem.read",), RiskLevel.READ_ONLY, 10.0, "on_demand")
GIT_STATUS = ToolManifest("programming.git_status", "Inspect Git status without changing repository state", ("filesystem.read",), RiskLevel.READ_ONLY, 15.0, "on_demand")
SEARCH = ToolManifest("programming.search", "Search bounded relevant source files", ("filesystem.read",), RiskLevel.READ_ONLY, 20.0, "on_demand")
DIAGNOSE = ToolManifest("programming.diagnose_startup", "Run a bounded project command and capture a structured startup failure", ("filesystem.read", "terminal.execute"), RiskLevel.MEDIUM, 120.0, "on_demand")
PATCH = ToolManifest("programming.apply_diagnostic_fix", "Checkpoint and apply one unambiguous diagnostic source fix", ("filesystem.read", "filesystem.write"), RiskLevel.MEDIUM, 20.0, "on_demand", True, "copy-target-before-patch")
VERIFY = ToolManifest("programming.verify_startup", "Rerun a bounded project command and verify successful startup completion", ("filesystem.read", "terminal.execute"), RiskLevel.MEDIUM, 120.0, "on_demand")
REPAIR = ToolManifest(
    "programming.repair_python", "Run a bounded diagnose/patch/test/replan loop for a local Python project",
    ("filesystem.read", "filesystem.write", "terminal.execute"), RiskLevel.MEDIUM, 300.0,
    "heavy_on_demand", True, "checkpoint-every-patch",
)
PLAN = ToolManifest("programming.plan", "Create a stack-aware project plan without writing files", ("filesystem.read",), RiskLevel.READ_ONLY, 10.0, "on_demand")
STATIC_VALIDATE = ToolManifest("programming.static_validate", "Validate planned files, local resource paths and accidental secrets", ("filesystem.read",), RiskLevel.READ_ONLY, 30.0, "on_demand")
LANGUAGE_ROUTE = ToolManifest("programming.language_route", "Resolve programming languages separately from project type", (), RiskLevel.READ_ONLY, 5.0, "on_demand")
TOOLCHAIN = ToolManifest("programming.toolchain", "Lazily detect one installed programming toolchain and version", ("terminal.execute",), RiskLevel.READ_ONLY, 10.0, "on_demand")


class DetectTool:
    manifest = DETECT
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = ProjectDetector().detect(str(arguments.get("path", ""))).public()
        return ToolResult(True, data, evidence={"markers_found": len(data["markers"]), "entrypoints": len(data["entrypoints"])})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.data.get("root") and (result.evidence.get("markers_found") or result.data.get("git")))


class GitStatusTool:
    manifest = GIT_STATUS
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = git_status(str(arguments.get("root", "")))
        return ToolResult(True, data, evidence={"inspected": True, "user_changes_preserved": True})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("inspected") and result.evidence.get("user_changes_preserved"))


class SearchTool:
    manifest = SEARCH
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = search_code(str(arguments.get("root", "")), str(arguments.get("query", "")), regex=bool(arguments.get("regex", False)), limit=int(arguments.get("limit", 100)))
        return ToolResult(True, data, evidence={"searched": True, "matches": len(data["matches"])})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("searched"))


class DiagnoseTool:
    manifest = DIAGNOSE
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        command = arguments.get("command", ())
        if not isinstance(command, (list, tuple)):
            raise ValueError("command_must_be_argv")
        data = diagnose_python_failure(str(arguments.get("root", "")), tuple(str(item) for item in command), timeout_seconds=float(arguments.get("timeout_seconds", 30)))
        reproduced = bool(data["failure_reproduced"])
        return ToolResult(reproduced, data, error=None if reproduced else "startup_failure_not_reproduced", error_code=None if reproduced else "not_reproduced", evidence={"failure_reproduced": reproduced, "process_cleanup_verified": data["process_cleanup_verified"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("failure_reproduced") and result.evidence.get("process_cleanup_verified"))


class PatchTool:
    manifest = PATCH
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = apply_name_error_fix(
            str(arguments.get("root", "")), str(arguments.get("relative_file", "")),
            int(arguments.get("line", 0)), str(arguments.get("undefined_name", "")),
            str(arguments.get("suggested_name", "")),
        )
        return ToolResult(True, data, evidence={"checkpoint_created": bool(data["checkpoint"]), "reopened": data["reopened"], "diff_nonempty": bool(data["diff"])}, changed_state=data["changed_state"])
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("checkpoint_created") and result.evidence.get("reopened") and result.evidence.get("diff_nonempty"))


class VerifyTool:
    manifest = VERIFY
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        command = arguments.get("command", ())
        if not isinstance(command, (list, tuple)):
            raise ValueError("command_must_be_argv")
        data = run_bounded(str(arguments.get("root", "")), tuple(str(item) for item in command), timeout_seconds=float(arguments.get("timeout_seconds", 30)))
        success = data["exit_code"] == 0 and not data["timed_out"] and data["process_cleanup_verified"]
        return ToolResult(success, data, error=None if success else "startup_still_failing", error_code=None if success else "nonzero_exit", evidence={"exit_code": data["exit_code"], "process_cleanup_verified": data["process_cleanup_verified"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("exit_code") == 0 and result.evidence.get("process_cleanup_verified"))


class RepairTool:
    manifest = REPAIR
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = repair_python_project(
            str(arguments.get("root", "")),
            max_iterations=int(arguments.get("max_iterations", 8)),
            timeout_seconds=float(arguments.get("timeout_seconds", 30)),
        )
        completed = data["status"] == "completed"
        return ToolResult(
            completed, data, error=None if completed else str(data.get("error") or "repair_blocked"),
            error_code=None if completed else "repair_blocked",
            evidence={"tests_verified": data["tests_verified"],
                      "startup_verified": data["startup_verified"],
                      "process_cleanup_verified": data["process_cleanup_verified"],
                      "checkpoints": len(data["patches"])},
            changed_state=bool(data["patches"]),
        )
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("tests_verified") and result.evidence.get("startup_verified")
                    and result.evidence.get("process_cleanup_verified"))


class PlanTool:
    manifest = PLAN
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        root = str(arguments.get("root", "")) or None
        data = ProjectPlanner().plan(str(arguments.get("request", "")), root=root).public()
        return ToolResult(True, data, evidence={"planned": True, "writes": 0, "existing_project": data["existing_project"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("planned") and result.data.get("stack") and result.data.get("requirements"))


class StaticValidateTool:
    manifest = STATIC_VALIDATE
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        root = str(arguments.get("root", ""))
        plan = ProjectPlanner().plan(str(arguments.get("request", "")), root=root)
        data = ProjectCompletionGate().validate(root, plan)
        return ToolResult(bool(data["passed"]), data, error=None if data["passed"] else "static_validation_failed", evidence={"static_validation": data["passed"], "runtime_verified": False})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("static_validation") and result.data.get("status") == "STATIC VALIDATED")


class LanguageRouteTool:
    manifest = LANGUAGE_ROUTE
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        request = str(arguments.get("request", ""))
        profiles = ProgrammingLanguageRouter().route(request)
        project = ProjectTypeResolver().resolve(request)
        data = {
            "languages": [profile.public() for profile in profiles],
            "project_type": project.project_type, "framework": project.framework,
            "runtime": project.runtime,
        }
        return ToolResult(True, data, evidence={"language_project_type_separated": True})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("language_project_type_separated") and result.data.get("project_type"))


class ToolchainTool:
    manifest = TOOLCHAIN
    _detector = ToolchainDetector()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self._detector.detect(str(arguments.get("name", "")), include_version=bool(arguments.get("include_version", True)))
        return ToolResult(True, data, evidence={"probe_requested": True, "lazy": True})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("probe_requested") and result.data.get("name"))


class ProgrammingAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("programming_agent")
        self.tools = tools
    def _start(self) -> None:
        self.tools.register(LANGUAGE_ROUTE, LanguageRouteTool)
        self.tools.register(TOOLCHAIN, ToolchainTool)
        self.tools.register(PLAN, PlanTool)
        self.tools.register(STATIC_VALIDATE, StaticValidateTool)
        self.tools.register(DETECT, DetectTool)
        self.tools.register(GIT_STATUS, GitStatusTool)
        self.tools.register(SEARCH, SearchTool)
        self.tools.register(DIAGNOSE, DiagnoseTool)
        self.tools.register(PATCH, PatchTool)
        self.tools.register(VERIFY, VerifyTool)
        self.tools.register(REPAIR, RepairTool)
    def _stop(self) -> None:
        for manifest in (TOOLCHAIN, LANGUAGE_ROUTE, STATIC_VALIDATE, PLAN, REPAIR, VERIFY, PATCH, DIAGNOSE, SEARCH, GIT_STATUS, DETECT):
            self.tools.unregister(manifest.id)
