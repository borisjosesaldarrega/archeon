"""Permission-gated, cited search tool around the existing lazy provider."""

from __future__ import annotations

from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .engine import SearchEngine


SEARCH = ToolManifest("search.query", "Retrieve bounded current results with source URLs and timestamps", ("network.search",), RiskLevel.READ_ONLY, 20.0, "on_demand")


class SearchTool:
    manifest = SEARCH
    def __init__(self, search: SearchEngine) -> None: self.search = search
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        results = self.search.search(
            str(arguments.get("query", "")), limit=max(1, min(int(arguments.get("limit", 5)), 10)),
            language=str(arguments.get("language", "es")), freshness=str(arguments.get("freshness")) if arguments.get("freshness") else None,
        )
        data = {"query": str(arguments.get("query", "")), "results": results, "count": len(results)}
        return ToolResult(bool(results), data, error=None if results else "search_no_verified_results", evidence={"sources": len(results), "urls": [item["url"] for item in results]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("sources", 0) > 0 and all(str(url).startswith(("http://", "https://")) for url in result.evidence.get("urls", [])))


class SearchAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine, search: SearchEngine) -> None:
        super().__init__("search_agent"); self.tools = tools; self.search = search
    def _start(self) -> None: self.tools.register(SEARCH, lambda: SearchTool(self.search))
    def _stop(self) -> None: self.tools.unregister(SEARCH.id)
