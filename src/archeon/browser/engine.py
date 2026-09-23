"""Permission-gated DOM-first browser tools sharing one lazy session."""

from __future__ import annotations

from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult

from .session import BrowserSession
from .visible import VisibleBrowserSession


NAVIGATE = ToolManifest("browser.navigate", "Navigate an HTTPS page and parse its DOM locally", ("network.browser",), RiskLevel.READ_ONLY, 30.0, "on_demand")
READ = ToolManifest("browser.read", "Read the current DOM page text", ("network.browser",), RiskLevel.READ_ONLY, 10.0, "on_demand")
FIND = ToolManifest("browser.find", "Find text in the current DOM page", ("network.browser",), RiskLevel.READ_ONLY, 10.0, "on_demand")
CLICK = ToolManifest("browser.click_link", "Follow one unambiguous HTTPS DOM link", ("network.browser",), RiskLevel.LOW, 30.0, "on_demand")
HISTORY = ToolManifest("browser.history", "Navigate back or forward in the active browser tab", ("network.browser",), RiskLevel.LOW, 30.0, "on_demand")
TABS = ToolManifest("browser.tabs", "Create, close or switch bounded browser tabs", ("network.browser",), RiskLevel.LOW, 30.0, "on_demand")
DOWNLOAD = ToolManifest("browser.download", "Stream an HTTPS download to an explicit new local file", ("network.browser", "filesystem.write"), RiskLevel.MEDIUM, 120.0, "on_demand", True, "record-created-download")
TYPE_FIELD = ToolManifest("browser.type_field", "Set a non-secret accessible DOM form field", ("network.browser",), RiskLevel.LOW, 10.0, "on_demand")
SCROLL = ToolManifest("browser.scroll", "Move the bounded DOM reading viewport", ("network.browser",), RiskLevel.LOW, 10.0, "on_demand")
UPLOAD = ToolManifest("browser.upload", "Submit one explicit local file through an accessible DOM file input", ("network.browser", "filesystem.read"), RiskLevel.MEDIUM, 120.0, "on_demand")
RELOAD = ToolManifest("browser.reload", "Reload the active HTTPS page and compare its DOM", ("network.browser",), RiskLevel.LOW, 30.0, "on_demand")
SET_CONTROL = ToolManifest("browser.set_control", "Set an accessible select, checkbox or radio control", ("network.browser",), RiskLevel.LOW, 10.0, "on_demand")
SUBMIT_FORM = ToolManifest("browser.submit_form", "Submit one accessible non-secret DOM form", ("network.browser",), RiskLevel.MEDIUM, 30.0, "on_demand")
SCROLL_UNTIL = ToolManifest("browser.scroll_until", "Scroll, reload and paginate within strict bounds until a goal is found", ("network.browser",), RiskLevel.LOW, 60.0, "on_demand")
OPEN_VISIBLE = ToolManifest("browser.open_visible", "Open an isolated visible browser window with its accessibility tree enabled", ("network.browser", "desktop.control"), RiskLevel.LOW, 30.0, "on_demand")
VERIFY_VISIBLE_SEARCH = ToolManifest("browser.verify_visible_search", "Verify a visible browser search results page from its accessibility tree", ("network.browser", "desktop.observe"), RiskLevel.READ_ONLY, 15.0, "on_demand")
LOCATE_VISIBLE_SEARCH = ToolManifest("browser.locate_visible_search", "Locate the visible browser search field through its accessibility tree", ("network.browser", "desktop.observe"), RiskLevel.READ_ONLY, 10.0, "on_demand")


class _Base:
    def __init__(self, session: BrowserSession) -> None: self.session = session


class NavigateTool(_Base):
    manifest = NAVIGATE
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.navigate(str(arguments.get("url", "")))
        return ToolResult(True, data, evidence={"https": data["url"].startswith("https://"), "status": data["status"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("https") and 200 <= result.evidence.get("status", 0) < 400)


class ReadTool(_Base):
    manifest = READ
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.read(max_characters=int(arguments.get("max_characters", 100_000)))
        return ToolResult(True, data, evidence={"url": data["url"], "characters": len(data["text"])})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("url") and "text" in result.data)


class FindTool(_Base):
    manifest = FIND
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.find(str(arguments.get("query", "")), limit=int(arguments.get("limit", 30)))
        return ToolResult(True, data, evidence={"searched": True, "matches": len(data["matches"])})
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("searched") and result.evidence.get("matches", 0) > 0)


class ClickTool(_Base):
    manifest = CLICK
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        before = self.session.current.url; data = self.session.click_link(str(arguments.get("text", "")))
        return ToolResult(True, data, evidence={"url_changed": before != data["url"], "https": data["url"].startswith("https://")}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("url_changed") and result.evidence.get("https"))


class HistoryTool(_Base):
    manifest = HISTORY
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "")); data = self.session.back() if action == "back" else self.session.forward() if action == "forward" else None
        if data is None: raise ValueError("invalid_history_action")
        return ToolResult(True, data, evidence={"navigated": True}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("navigated"))


class TabsTool(_Base):
    manifest = TABS
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        action = str(arguments.get("action", ""))
        if action == "new": data = self.session.new_tab(str(arguments.get("url", "")))
        elif action == "switch": data = self.session.switch_tab(str(arguments.get("tab_id", "")))
        elif action == "close": data = self.session.close_tab(str(arguments.get("tab_id", "")))
        else: raise ValueError("invalid_tab_action")
        return ToolResult(True, data, evidence={"tab_id": data["id"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("tab_id"))


class DownloadTool(_Base):
    manifest = DOWNLOAD
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.download(str(arguments.get("url", "")), str(arguments.get("destination", "")))
        return ToolResult(True, data, evidence={"file_exists": data["verified"], "bytes": data["bytes"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("file_exists") and result.evidence.get("bytes", 0) > 0)


class TypeFieldTool(_Base):
    manifest = TYPE_FIELD
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.type_field(str(arguments.get("name", "")), str(arguments.get("value", "")))
        return ToolResult(True, data, evidence={"value_set": data["value_set"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("value_set"))


class ScrollTool(_Base):
    manifest = SCROLL
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.scroll(int(arguments.get("characters", 10_000)))
        return ToolResult(True, data, evidence={"offset": data["after"]}, changed_state=data["changed"])
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return "offset" in result.evidence


class UploadTool(_Base):
    manifest = UPLOAD
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.upload(str(arguments.get("file", "")), form_index=int(arguments.get("form_index", 0)), file_field=str(arguments.get("file_field", "")))
        return ToolResult(data["submitted"], data, error=None if data["submitted"] else "browser_upload_failed", evidence={"submitted": data["submitted"], "status": data["status"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("submitted"))


class ReloadTool(_Base):
    manifest = RELOAD
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.reload()
        return ToolResult(True, data, evidence={"reloaded": data["reloaded"], "status": data["status"]}, changed_state=data["dom_changed"])
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("reloaded") and 200 <= result.evidence.get("status", 0) < 400)


class SetControlTool(_Base):
    manifest = SET_CONTROL
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        checked = arguments.get("checked")
        data = self.session.set_control(
            str(arguments.get("name", "")), value=str(arguments.get("value", "")),
            checked=None if checked is None else bool(checked),
        )
        return ToolResult(True, data, evidence={"control_set": data["control_set"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("control_set"))


class SubmitFormTool(_Base):
    manifest = SUBMIT_FORM
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.submit_form(
            form_index=int(arguments.get("form_index", 0)), submit_name=str(arguments.get("submit_name", "")),
        )
        return ToolResult(True, data, evidence={"status": data["status"], "url": data["url"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return bool(result.evidence.get("url") and 200 <= result.evidence.get("status", 0) < 400)


class ScrollUntilTool(_Base):
    manifest = SCROLL_UNTIL
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.scroll_until(
            str(arguments.get("query", "")), step_characters=int(arguments.get("step_characters", 10_000)),
            max_steps=int(arguments.get("max_steps", 12)), allow_pagination=bool(arguments.get("allow_pagination", True)),
            reload_dynamic=bool(arguments.get("reload_dynamic", True)),
        )
        return ToolResult(True, data, evidence={"goal_found": data["found"], "steps": data["steps"]}, changed_state=bool(data["observations"]))
    def verify(self, context: ToolContext, result: ToolResult) -> bool: return "goal_found" in result.evidence


class OpenVisibleTool:
    manifest = OPEN_VISIBLE
    def __init__(self, session: VisibleBrowserSession) -> None: self.session = session
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.open(str(arguments.get("url", "")), timeout_seconds=float(arguments.get("timeout_seconds", 15.0)))
        return ToolResult(True, data, evidence={"window_handle": data["window"]["handle"], "page_root_seen": data["page_root_seen"], "interactive_ready": data["interactive_ready"]}, changed_state=True)
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("window_handle") and result.evidence.get("page_root_seen") and result.evidence.get("interactive_ready"))


class VerifyVisibleSearchTool:
    manifest = VERIFY_VISIBLE_SEARCH
    def __init__(self, session: VisibleBrowserSession) -> None: self.session = session
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.verify_search_results(str(arguments.get("query", "")))
        return ToolResult(
            bool(data["verified"]), data,
            error=None if data["verified"] else "visible_search_not_verified",
            evidence={"query_visible": data["query_visible"], "result_count": data["result_count"]},
        )
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("query_visible") and result.evidence.get("result_count", 0) > 0)


class LocateVisibleSearchTool:
    manifest = LOCATE_VISIBLE_SEARCH
    def __init__(self, session: VisibleBrowserSession) -> None: self.session = session
    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        data = self.session.locate_search()
        return ToolResult(True, data, evidence={"bounds": data["bounds"], "method": data["perception_method"]})
    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        bounds = result.data.get("bounds", ())
        return bool(len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1])


class BrowserAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("browser_agent"); self.tools = tools; self.session = BrowserSession(); self.visible = VisibleBrowserSession()
    def _start(self) -> None:
        self.tools.register(NAVIGATE, lambda: NavigateTool(self.session)); self.tools.register(READ, lambda: ReadTool(self.session))
        self.tools.register(FIND, lambda: FindTool(self.session)); self.tools.register(CLICK, lambda: ClickTool(self.session))
        self.tools.register(HISTORY, lambda: HistoryTool(self.session)); self.tools.register(TABS, lambda: TabsTool(self.session))
        self.tools.register(DOWNLOAD, lambda: DownloadTool(self.session))
        self.tools.register(TYPE_FIELD, lambda: TypeFieldTool(self.session)); self.tools.register(SCROLL, lambda: ScrollTool(self.session))
        self.tools.register(UPLOAD, lambda: UploadTool(self.session))
        self.tools.register(RELOAD, lambda: ReloadTool(self.session)); self.tools.register(SET_CONTROL, lambda: SetControlTool(self.session))
        self.tools.register(SUBMIT_FORM, lambda: SubmitFormTool(self.session)); self.tools.register(SCROLL_UNTIL, lambda: ScrollUntilTool(self.session))
        self.tools.register(OPEN_VISIBLE, lambda: OpenVisibleTool(self.visible)); self.tools.register(VERIFY_VISIBLE_SEARCH, lambda: VerifyVisibleSearchTool(self.visible))
        self.tools.register(LOCATE_VISIBLE_SEARCH, lambda: LocateVisibleSearchTool(self.visible))
    def _stop(self) -> None:
        for manifest in (LOCATE_VISIBLE_SEARCH, VERIFY_VISIBLE_SEARCH, OPEN_VISIBLE, SCROLL_UNTIL, SUBMIT_FORM, SET_CONTROL, RELOAD, UPLOAD, SCROLL, TYPE_FIELD, DOWNLOAD, TABS, HISTORY, CLICK, FIND, READ, NAVIGATE): self.tools.unregister(manifest.id)
        self.visible.close()
