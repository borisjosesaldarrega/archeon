"""Permission-gated generic artifact tools."""

from __future__ import annotations

from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .models import ArtifactSpec
from .provider import ArtifactProvider
from .archive_intelligence import ArchiveEngineProvider
from .quality import ArtifactQualityEngine
from .quality_advanced import ArtifactQualityEngineV2


CREATE = ToolManifest(
    "artifacts.create", "Create and reopen one structured artifact", ("filesystem.write",),
    RiskLevel.LOW, 60.0, "on_demand", True, "delete-created-artifact",
)
INSPECT = ToolManifest(
    "artifacts.inspect", "Read bounded structural information from one artifact", ("filesystem.read",),
    RiskLevel.READ_ONLY, 30.0, "on_demand",
)
EDIT = ToolManifest(
    "artifacts.edit_copy", "Checkpoint an artifact and save one verified edited copy",
    ("filesystem.read", "filesystem.write"), RiskLevel.LOW, 60.0, "on_demand", True,
    "backup-source-before-edit-copy",
)
VERIFY = ToolManifest(
    "artifacts.verify", "Reopen an artifact and validate its structure and digest", ("filesystem.read",),
    RiskLevel.READ_ONLY, 30.0, "on_demand",
)
QUALITY_REVIEW = ToolManifest(
    "artifacts.quality_review", "Review post-render evidence and return targeted repairs",
    ("filesystem.read",), RiskLevel.READ_ONLY, 30.0, "on_demand",
)
ARCHIVE_CAPABILITIES = ToolManifest("archives.capabilities", "Report native and optional archive providers", (), RiskLevel.READ_ONLY, 5.0, "on_demand")
ARCHIVE_CREATE = ToolManifest("archives.create", "Create and integrity-test a bounded archive", ("filesystem.read", "filesystem.write"), RiskLevel.LOW, 120.0, "on_demand", True, "delete-created-archive")
ARCHIVE_LIST = ToolManifest("archives.list", "List bounded archive members without extracting", ("filesystem.read",), RiskLevel.READ_ONLY, 30.0, "on_demand")
ARCHIVE_READ = ToolManifest("archives.read_member", "Read one bounded archive member without extracting the archive", ("filesystem.read",), RiskLevel.READ_ONLY, 30.0, "on_demand")
ARCHIVE_ANALYZE = ToolManifest("archives.analyze_project", "Recognize an archived project through bounded static inspection", ("filesystem.read",), RiskLevel.READ_ONLY, 30.0, "on_demand")
ARCHIVE_VERIFY = ToolManifest("archives.verify", "Test archive integrity and calculate its digest", ("filesystem.read",), RiskLevel.READ_ONLY, 120.0, "on_demand")
ARCHIVE_EXTRACT = ToolManifest("archives.extract", "Extract a validated archive into one new directory", ("filesystem.read", "filesystem.write"), RiskLevel.MEDIUM, 180.0, "on_demand", True, "delete-created-extraction")


class CreateArtifactTool:
    manifest = CREATE
    def __init__(self) -> None: self.provider = ArtifactProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.create(ArtifactSpec.from_mapping(dict(arguments))).public()
        return ToolResult(data["verified"], data, evidence={"reopened": data["verified"], "sha256": data["sha256"], "bytes": data["bytes"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("reopened") and result.evidence.get("sha256") and result.evidence.get("bytes", 0) > 0)


class InspectArtifactTool:
    manifest = INSPECT
    def __init__(self) -> None: self.provider = ArtifactProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.inspect(str(arguments.get("path", "")))
        return ToolResult(bool(data.get("valid")), data, evidence={"valid": data.get("valid", False)})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("valid"))


class EditArtifactTool:
    manifest = EDIT
    def __init__(self) -> None: self.provider = ArtifactProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        replacements = arguments.get("replacements", {})
        cell_updates = arguments.get("cell_updates", {})
        if not isinstance(replacements, Mapping) or not isinstance(cell_updates, Mapping):
            raise ValueError("artifact_edits_must_be_mappings")
        data = self.provider.edit_copy(
            str(arguments.get("source", "")), str(arguments.get("output", "")),
            replacements={str(key): str(value) for key, value in replacements.items()},
            append=str(arguments.get("append", "")), cell_updates=dict(cell_updates),
        ).public()
        return ToolResult(data["verified"], data, evidence={"checkpoint": bool(data["checkpoint"]), "reopened": data["verified"], "sha256": data["sha256"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("checkpoint") and result.evidence.get("reopened") and result.evidence.get("sha256"))


class VerifyArtifactTool:
    manifest = VERIFY
    def __init__(self) -> None: self.provider = ArtifactProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.verify(str(arguments.get("path", ""))).public()
        return ToolResult(data["verified"], data, evidence={"valid": data["verified"], "sha256": data["sha256"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("valid") and result.evidence.get("sha256"))


class QualityReviewTool:
    manifest = QUALITY_REVIEW
    def __init__(self) -> None: self.engine = ArtifactQualityEngineV2()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        evidence = arguments.get("evidence", {})
        if not isinstance(evidence, Mapping): raise ValueError("quality_evidence_must_be_mapping")
        data = self.engine.review(str(arguments.get("artifact", "artifact")), evidence).public()
        return ToolResult(True, data, evidence={"reviewed": True, "issues": len(data["issues"]), "passed": data["passed"], "gate": data["gate"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("reviewed"))


class ArchiveCapabilitiesTool:
    manifest = ARCHIVE_CAPABILITIES
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.capabilities(); return ToolResult(True, data, evidence={"native": data["zip"]["available"] and data["tar"]["available"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("native"))


class ArchiveCreateTool:
    manifest = ARCHIVE_CREATE
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.create(str(arguments.get("destination", "")), [str(item) for item in arguments.get("sources", [])])
        return ToolResult(data["valid"], data, evidence={"integrity": data["valid"], "sha256": data["sha256"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("integrity") and result.evidence.get("sha256"))


class ArchiveListTool:
    manifest = ARCHIVE_LIST
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.list(str(arguments.get("path", ""))); return ToolResult(True, data, evidence={"listed": True, "members": data["member_count"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("listed"))


class ArchiveReadMemberTool:
    manifest = ARCHIVE_READ
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.read_member(
            str(arguments.get("path", "")), str(arguments.get("member", "")),
            password=str(arguments["password"]) if arguments.get("password") else None,
            max_bytes=int(arguments.get("max_bytes", self.provider.MAX_MEMBER_READ_BYTES)),
        )
        return ToolResult(True, data, evidence={"member_read": True, "sha256": data["sha256"], "executed": False})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("member_read") and result.evidence.get("sha256") and not result.evidence.get("executed"))


class ArchiveAnalyzeProjectTool:
    manifest = ARCHIVE_ANALYZE
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.analyze_project(str(arguments.get("path", "")))
        return ToolResult(True, data, evidence={"static_only": data["static_only"], "executed": data["executed"], "project_type": data["project_type"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("static_only") and not result.evidence.get("executed") and result.evidence.get("project_type"))


class ArchiveVerifyTool:
    manifest = ARCHIVE_VERIFY
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.verify(str(arguments.get("path", ""))); return ToolResult(data["valid"], data, evidence={"integrity": data["valid"], "sha256": data["sha256"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("integrity") and result.evidence.get("sha256"))


class ArchiveExtractTool:
    manifest = ARCHIVE_EXTRACT
    def __init__(self) -> None: self.provider = ArchiveEngineProvider()
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.provider.extract(
            str(arguments.get("path", "")), str(arguments.get("destination", "")),
            members=tuple(str(item) for item in arguments.get("members", ())) or None,
            password=str(arguments["password"]) if arguments.get("password") else None,
        )
        return ToolResult(data["verified"], data, evidence={"verified": data["verified"], "files": data["files"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("verified"))


class ArtifactEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("artifact_engine"); self.tools = tools
    def _start(self) -> None:
        self.tools.register(CREATE, CreateArtifactTool); self.tools.register(INSPECT, InspectArtifactTool)
        self.tools.register(EDIT, EditArtifactTool); self.tools.register(VERIFY, VerifyArtifactTool); self.tools.register(QUALITY_REVIEW, QualityReviewTool)
        self.tools.register(ARCHIVE_CAPABILITIES, ArchiveCapabilitiesTool); self.tools.register(ARCHIVE_CREATE, ArchiveCreateTool)
        self.tools.register(ARCHIVE_LIST, ArchiveListTool); self.tools.register(ARCHIVE_READ, ArchiveReadMemberTool); self.tools.register(ARCHIVE_ANALYZE, ArchiveAnalyzeProjectTool); self.tools.register(ARCHIVE_VERIFY, ArchiveVerifyTool)
        self.tools.register(ARCHIVE_EXTRACT, ArchiveExtractTool)
    def _stop(self) -> None:
        for manifest in (ARCHIVE_EXTRACT, ARCHIVE_VERIFY, ARCHIVE_ANALYZE, ARCHIVE_READ, ARCHIVE_LIST, ARCHIVE_CREATE, ARCHIVE_CAPABILITIES, QUALITY_REVIEW, VERIFY, EDIT, INSPECT, CREATE): self.tools.unregister(manifest.id)
