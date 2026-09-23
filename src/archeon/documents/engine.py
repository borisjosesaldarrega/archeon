"""Permission-gated tools for reading, searching and safely editing document copies."""

from __future__ import annotations

from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .editor import DocumentEditor
from .reader import DocumentReader


READ_MANIFEST = ToolManifest(
    id="documents.read", description="Read one bounded local document or exact PDF page",
    permissions=("filesystem.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=30.0,
    resource_class="on_demand",
)
SEARCH_MANIFEST = ToolManifest(
    id="documents.search", description="Search accessible text in one local document with page evidence",
    permissions=("filesystem.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=30.0,
    resource_class="on_demand",
)
EDIT_MANIFEST = ToolManifest(
    id="documents.edit_copy", description="Checkpoint a document and save a verified edited copy",
    permissions=("filesystem.read", "filesystem.write"), risk=RiskLevel.LOW, timeout_seconds=30.0,
    resource_class="on_demand", supports_rollback=True, checkpoint_policy="backup-source-before-edit-copy",
)
SUMMARY_MANIFEST = ToolManifest(
    id="documents.summarize", description="Extract a grounded title and bounded summary from one local document",
    permissions=("filesystem.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=30.0,
    resource_class="on_demand",
)


class ReadDocumentTool:
    manifest = READ_MANIFEST

    def __init__(self) -> None:
        self.reader = DocumentReader()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        raw_page = arguments.get("page")
        page = int(raw_page) if raw_page is not None else None
        page_range = None
        if arguments.get("page_start") is not None or arguments.get("page_end") is not None:
            page_range = (int(arguments.get("page_start", 1)), int(arguments.get("page_end", arguments.get("page_start", 1))))
        document = self.reader.read(str(arguments.get("path", "")), page=page, page_range=page_range)
        data = document.public(max_characters=max(1_024, min(int(arguments.get("max_characters", 200_000)), 1_000_000)))
        return ToolResult(
            True, data, evidence={
                "file_exists": True, "format": document.format,
                "page_count": document.metadata.get("page_count", len(document.pages)),
                "requested_pages": [item.number for item in document.pages],
                "accessible_text": all(item.accessible_text for item in document.pages),
            },
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("file_exists") and result.data.get("pages"))


class SearchDocumentTool:
    manifest = SEARCH_MANIFEST

    def __init__(self) -> None:
        self.reader = DocumentReader()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.reader.search(
            str(arguments.get("path", "")), str(arguments.get("query", "")),
            limit=int(arguments.get("limit", 50)),
        )
        return ToolResult(True, data, evidence={"searched": True, "matches": len(data["matches"])})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("searched") and "matches" in result.data)


class SummarizeDocumentTool:
    manifest = SUMMARY_MANIFEST

    def __init__(self) -> None:
        self.reader = DocumentReader()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        document = self.reader.read(str(arguments.get("path", "")))
        accessible = [page.text.strip() for page in document.pages if page.accessible_text and page.text.strip()]
        if not accessible:
            return ToolResult(False, error="document_has_no_accessible_text", error_code="visual_fallback_required")
        first_lines = [line.strip() for line in accessible[0].splitlines() if line.strip()]
        title = str(document.metadata.get("title") or (first_lines[0] if first_lines else document.path.stem)).strip()
        body = " ".join(" ".join(accessible).split())
        max_characters = max(160, min(int(arguments.get("max_characters", 1200)), 4000))
        summary = body[:max_characters].rstrip()
        if len(body) > len(summary):
            summary += "…"
        data = {"path": str(document.path), "title": title[:500], "summary": summary,
                "format": document.format, "page_count": len(document.pages)}
        return ToolResult(True, data, evidence={"accessible_text": True, "title_grounded": bool(title),
                                               "summary_characters": len(summary)})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("accessible_text") and result.evidence.get("title_grounded")
                    and result.data.get("summary"))


class EditDocumentCopyTool:
    manifest = EDIT_MANIFEST

    def __init__(self) -> None:
        self.editor = DocumentEditor()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        replacements = arguments.get("replacements", {})
        if not isinstance(replacements, Mapping):
            raise ValueError("replacements_must_be_mapping")
        data = self.editor.edit_copy(
            str(arguments.get("source", "")), str(arguments.get("output", "")),
            replacements={str(key): str(value) for key, value in replacements.items()},
            append_paragraphs=tuple(str(item) for item in arguments.get("append_paragraphs", ())),
            remove_paragraphs=tuple(int(item) for item in arguments.get("remove_paragraphs", ())),
        )
        return ToolResult(
            True, data, evidence={
                "checkpoint_created": bool(data["checkpoint"]),
                "output_reopened": data["reopened"], "modification_verified": data["verified"],
            }, changed_state=True,
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(
            result.evidence.get("checkpoint_created") and result.evidence.get("output_reopened")
            and result.evidence.get("modification_verified")
        )


class DocumentAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("document_agent")
        self.tools = tools

    def _start(self) -> None:
        self.tools.register(READ_MANIFEST, ReadDocumentTool)
        self.tools.register(SEARCH_MANIFEST, SearchDocumentTool)
        self.tools.register(SUMMARY_MANIFEST, SummarizeDocumentTool)
        self.tools.register(EDIT_MANIFEST, EditDocumentCopyTool)

    def _stop(self) -> None:
        self.tools.unregister(EDIT_MANIFEST.id)
        self.tools.unregister(SUMMARY_MANIFEST.id)
        self.tools.unregister(SEARCH_MANIFEST.id)
        self.tools.unregister(READ_MANIFEST.id)
