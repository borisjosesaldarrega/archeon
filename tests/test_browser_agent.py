from __future__ import annotations

import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from archeon.browser import BrowserSession
from archeon.browser.engine import BrowserAgentEngine
from archeon.browser.visible import VisibleBrowserSession
from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.permissions import PermissionEngine
from archeon.core.tools import ToolContext, ToolEngine


class FakeResponse(io.BytesIO):
    def __init__(self, url: str, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        super().__init__(body); self._url = url; self.status = 200
        self.headers = Message(); self.headers["Content-Type"] = content_type
    def geturl(self) -> str: return self._url
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()


class FakeOpener:
    def __init__(self, pages: dict[str, bytes]) -> None: self.pages = pages
    def open(self, request, timeout=0):
        url = request.full_url
        if url not in self.pages: raise OSError(f"unmapped URL: {url}")
        return FakeResponse(url, self.pages[url])


class SequencedOpener:
    def __init__(self, pages: list[bytes]) -> None:
        self.pages = pages; self.calls = 0
    def open(self, request, timeout=0):
        index = min(self.calls, len(self.pages) - 1); self.calls += 1
        return FakeResponse(request.full_url, self.pages[index])


class BrowserAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = {
            "https://docs.example/": b"<title>Docs</title><h1>Documentation</h1><a href='/pathlib.html'>pathlib</a><form action='/upload' method='post' enctype='multipart/form-data'><input name='description'><input type='file' name='attachment'></form>",
            "https://docs.example/pathlib.html": b"<title>pathlib</title><h1>Object-oriented filesystem paths</h1><p>Path objects represent filesystem paths.</p>",
            "https://docs.example/upload": b"<title>Uploaded</title><p>Success</p>",
        }
        self.session = BrowserSession(opener=FakeOpener(self.pages))

    def test_dom_navigation_link_history_tabs_and_find(self) -> None:
        first = self.session.navigate("https://docs.example/")
        second = self.session.click_link("pathlib")
        found = self.session.find("filesystem paths")
        back = self.session.back(); forward = self.session.forward()
        tab = self.session.new_tab("https://docs.example/")
        switched = self.session.switch_tab(first["id"])
        self.assertEqual(first["title"], "Docs")
        self.assertEqual(second["url"], "https://docs.example/pathlib.html")
        self.assertTrue(found["matches"])
        self.assertEqual(back["url"], "https://docs.example/")
        self.assertEqual(forward["url"], "https://docs.example/pathlib.html")
        self.assertNotEqual(tab["id"], first["id"])
        self.assertEqual(switched["id"], first["id"])

    def test_form_typing_scroll_and_explicit_upload_use_dom_inputs(self) -> None:
        self.session.navigate("https://docs.example/")
        typed = self.session.type_field("description", "controlled fixture")
        scrolled = self.session.scroll(10)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.txt"
            source.write_text("ARCHI upload fixture", encoding="utf-8")
            uploaded = self.session.upload(source, file_field="attachment")
        self.assertTrue(typed["value_set"])
        self.assertGreaterEqual(scrolled["after"], 0)
        self.assertTrue(uploaded["submitted"])
        self.assertEqual(uploaded["field"], "attachment")

    def test_insecure_url_and_oversized_page_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "https_url_required"):
            self.session.navigate("http://docs.example/")
        oversized = BrowserSession(opener=FakeOpener({"https://large.example/": b"x" * (5 * 1024 * 1024 + 1)}))
        with self.assertRaisesRegex(ValueError, "browser_response_too_large"):
            oversized.navigate("https://large.example/")

    def test_permission_gated_tools_share_lazy_session_and_verify_dom(self) -> None:
        temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
        config = ConfigurationManager(root / "config.json"); config.start()
        events = EventBus(); tools = ToolEngine(events, PermissionEngine(config))
        agent = BrowserAgentEngine(tools); agent.session = self.session
        agent.start(); tools.start()
        context = ToolContext("browser-test", scope_permissions=frozenset({"network.browser"}))
        try:
            denied = tools.execute("browser.navigate", {"url": "https://docs.example/"})
            navigated = tools.execute("browser.navigate", {"url": "https://docs.example/"}, context=context)
            clicked = tools.execute("browser.click_link", {"text": "pathlib"}, context=context)
            found = tools.execute("browser.find", {"query": "filesystem paths"}, context=context)
            self.assertFalse(denied.ok)
            self.assertTrue(navigated.verified and clicked.verified and found.verified)
            self.assertEqual(tools.loaded_tool_count, 3)
        finally:
            tools.stop(); agent.stop(); events.close(); config.stop(); temp.cleanup()

    def test_reload_select_checkbox_radio_and_form_submission(self) -> None:
        pages = {
            "https://forms.example/": b"""
                <title>Form</title><form action='/saved' method='post'>
                <select name='region'><option value='ec'>Ecuador</option><option value='mx'>Mexico</option></select>
                <input type='checkbox' name='alerts' value='yes'>
                <input type='radio' name='mode' value='archi'>
                <button name='save' value='1'>Save</button></form><dialog open>Confirm changes</dialog>
            """,
            "https://forms.example/saved": b"<title>Saved</title><p>Settings saved</p>",
        }
        session = BrowserSession(opener=FakeOpener(pages))
        opened = session.navigate("https://forms.example/")
        region = session.set_control("region", value="Mexico")
        alerts = session.set_control("alerts", checked=True)
        mode = session.set_control("mode", checked=True)
        saved = session.submit_form(submit_name="save")
        self.assertEqual(opened["dialog_count"], 1)
        self.assertEqual(region["value"], "mx")
        self.assertEqual(alerts["value"], "yes")
        self.assertEqual(mode["value"], "archi")
        self.assertEqual(saved["title"], "Saved")

    def test_reload_detects_dynamic_server_dom_change(self) -> None:
        session = BrowserSession(opener=SequencedOpener([
            b"<title>Jobs</title><p>Loading</p>",
            b"<title>Jobs</title><p>Asyncio Engineer</p>",
        ]))
        session.navigate("https://dynamic.example/")
        reloaded = session.reload()
        self.assertTrue(reloaded["dom_changed"])
        self.assertTrue(session.find("Asyncio Engineer")["matches"])

    def test_visible_youtube_verification_rejects_page_chrome_as_results(self) -> None:
        chrome = [
            {"name": "Buscar", "automation_id": "", "class_name": "ytSearchboxComponentInput", "control_type": 50003},
            {"name": "Principal", "automation_id": "endpoint", "class_name": "ytd-mini-guide-entry-renderer", "control_type": 50005},
            {"name": "Filtros de búsqueda", "automation_id": "", "class_name": "ytSpecButtonShapeNextHost", "control_type": 50000},
        ]
        self.assertEqual(VisibleBrowserSession._youtube_result_elements(chrome), [])

    def test_visible_youtube_verification_accepts_real_video_and_short_results(self) -> None:
        results = [
            {"name": "OpenAI demo 2 minutos", "automation_id": "video-title", "class_name": "yt-simple-endpoint style-scope ytd-video-renderer", "control_type": 50005},
            {"name": "OpenAI Short", "automation_id": "", "class_name": "shortsLockupViewModelHostEndpoint", "control_type": 50005},
        ]
        self.assertEqual(len(VisibleBrowserSession._youtube_result_elements(results)), 2)


class BrowserDynamicScrollTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_bounded_scroll_reloads_and_uses_next_page_until_goal(self) -> None:
        pages = {
            "https://jobs.example/": b"<title>Jobs 1</title><p>Older roles</p><a href='/page2'>Next</a>",
            "https://jobs.example/page2": b"<title>Jobs 2</title><p>Senior Python asyncio developer</p>",
        }
        session = BrowserSession(opener=FakeOpener(pages))
        session.navigate("https://jobs.example/")
        result = await session.scroll_until_async("asyncio", max_steps=6, step_characters=1000)
        self.assertTrue(result["found"])
        self.assertEqual(result["tab"]["url"], "https://jobs.example/page2")
        self.assertLessEqual(result["steps"], 6)
        self.assertTrue(any(item["action"] == "next_page" for item in result["observations"]))


if __name__ == "__main__": unittest.main()
