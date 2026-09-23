"""Small HTTPS DOM session with bounded tabs, history and downloads."""

from __future__ import annotations

import asyncio
import hashlib
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4


class _DOM(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._hidden = 0
        self.text: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.dialogs: list[str] = []
        self._link: dict[str, Any] | None = None
        self._form: dict[str, Any] | None = None
        self._select: dict[str, Any] | None = None
        self._option: dict[str, Any] | None = None
        self._dialog_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and values.get("href"):
            self._link = {"href": values["href"], "parts": []}
        if tag == "form":
            self._form = {
                "action": values.get("action", ""), "method": values.get("method", "get").casefold(),
                "enctype": values.get("enctype", "application/x-www-form-urlencoded"), "inputs": [],
            }
        if tag == "input" and self._form is not None and values.get("name"):
            self._form["inputs"].append({
                "name": values["name"], "type": values.get("type", "text").casefold(),
                "value": values.get("value", ""), "checked": "checked" in values,
                "disabled": "disabled" in values,
            })
        if tag == "select" and self._form is not None and values.get("name"):
            self._select = {
                "name": values["name"], "type": "select", "value": "", "options": [],
                "multiple": "multiple" in values, "disabled": "disabled" in values,
            }
            self._form["inputs"].append(self._select)
        if tag == "option" and self._select is not None:
            self._option = {
                "value": values.get("value", ""), "label_parts": [], "selected": "selected" in values,
            }
        if tag == "textarea" and self._form is not None and values.get("name"):
            self._form["inputs"].append({
                "name": values["name"], "type": "textarea", "value": "",
                "disabled": "disabled" in values,
            })
        if tag == "button" and self._form is not None:
            self._form["inputs"].append({
                "name": values.get("name", ""), "type": values.get("type", "submit"),
                "value": values.get("value", ""), "disabled": "disabled" in values,
            })
        if tag == "dialog":
            self._dialog_parts = []
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr"}:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._link:
            label = " ".join(self._link["parts"]).strip()
            self.links.append({"text": label, "href": str(self._link["href"])})
            self._link = None
        if tag == "form" and self._form is not None:
            self.forms.append(self._form); self._form = None
        if tag == "option" and self._option is not None and self._select is not None:
            label = " ".join(self._option["label_parts"]).strip()
            if not self._option["value"]:
                self._option["value"] = label
            self._option["label"] = label
            self._select["options"].append(self._option)
            if self._option["selected"] or not self._select["value"]:
                self._select["value"] = self._option["value"]
            self._option = None
        if tag == "select":
            self._select = None
        if tag == "dialog" and self._dialog_parts is not None:
            value = " ".join(self._dialog_parts).strip()
            if value:
                self.dialogs.append(value[:2_000])
            self._dialog_parts = None

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title += (" " if self.title else "") + value
        self.text.append(value + " ")
        if self._link is not None:
            self._link["parts"].append(value)
        if self._option is not None:
            self._option["label_parts"].append(value)
        if self._dialog_parts is not None:
            self._dialog_parts.append(value)


@dataclass(slots=True)
class BrowserTab:
    id: str = field(default_factory=lambda: uuid4().hex)
    url: str = "about:blank"
    title: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    status: int = 0
    forms: list[dict[str, Any]] = field(default_factory=list)
    form_values: dict[str, str] = field(default_factory=dict)
    scroll_offset: int = 0
    dialogs: list[str] = field(default_factory=list)
    dom_hash: str = ""

    def public(self, *, include_text: bool = False) -> dict[str, Any]:
        value = {
            "id": self.id, "url": self.url, "title": self.title, "status": self.status,
            "link_count": len(self.links), "history_index": self.history_index,
            "form_count": len(self.forms), "scroll_offset": self.scroll_offset,
            "dialog_count": len(self.dialogs), "dom_hash": self.dom_hash,
        }
        if include_text:
            value["text"] = self.text
        return value


class BrowserSession:
    MAX_RESPONSE_BYTES = 5 * 1024 * 1024
    MAX_TEXT_CHARACTERS = 1_000_000

    def __init__(self, *, opener: Any | None = None) -> None:
        self._opener = opener or urllib.request.build_opener()
        self._tabs: list[BrowserTab] = [BrowserTab()]
        self._active = 0

    @property
    def current(self) -> BrowserTab:
        return self._tabs[self._active]

    def navigate(self, url: str, *, record_history: bool = True) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise ValueError("https_url_required")
        request = urllib.request.Request(
            url, headers={"User-Agent": "ARCHEON/10 Desktop BrowserAgent", "Accept": "text/html,application/xhtml+xml"},
        )
        with self._opener.open(request, timeout=15) as response:
            final_url = response.geturl()
            if urllib.parse.urlsplit(final_url).scheme.casefold() != "https":
                raise ValueError("insecure_redirect_rejected")
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("browser_content_type_not_html")
            raw = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(raw) > self.MAX_RESPONSE_BYTES:
                raise ValueError("browser_response_too_large")
            encoding = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(encoding, "replace")
            status = int(getattr(response, "status", 200))
        return self._apply_html(final_url, html, status, record_history=record_history)

    def _apply_html(
        self, final_url: str, html: str, status: int, *, record_history: bool,
    ) -> dict[str, Any]:
        dom = _DOM(); dom.feed(html)
        tab = self.current
        tab.url = final_url
        tab.title = dom.title[:500]
        tab.text = re.sub(r"\n{3,}", "\n\n", "".join(dom.text)).strip()[:self.MAX_TEXT_CHARACTERS]
        tab.links = [
            {"text": item["text"][:500], "url": urllib.parse.urljoin(final_url, item["href"])}
            for item in dom.links
            if urllib.parse.urlsplit(urllib.parse.urljoin(final_url, item["href"])).scheme == "https"
        ][:5000]
        tab.forms = dom.forms[:100]
        tab.dialogs = dom.dialogs[:50]
        tab.dom_hash = hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()
        tab.form_values.clear(); tab.scroll_offset = 0
        tab.status = status
        if record_history:
            del tab.history[tab.history_index + 1:]
            tab.history.append(final_url)
            tab.history_index = len(tab.history) - 1
        return tab.public()

    def reload(self) -> dict[str, Any]:
        if not self.current.url.startswith("https://"):
            raise RuntimeError("browser_tab_not_navigated")
        before_hash = self.current.dom_hash
        data = self.navigate(self.current.url, record_history=False)
        data["reloaded"] = True
        data["dom_changed"] = data["dom_hash"] != before_hash
        return data

    def read(self, *, max_characters: int = 100_000) -> dict[str, Any]:
        tab = self.current
        limit = max(1_000, min(max_characters, self.MAX_TEXT_CHARACTERS))
        text = tab.text[tab.scroll_offset:tab.scroll_offset + limit]
        return {**tab.public(), "text": text, "truncated": len(text) < len(tab.text)}

    def find(self, query: str, *, limit: int = 30) -> dict[str, Any]:
        needle = query.casefold().strip()
        if not needle:
            raise ValueError("browser_find_query_required")
        matches = []
        for line_number, line in enumerate(self.current.text.splitlines(), 1):
            offset = line.casefold().find(needle)
            if offset >= 0:
                matches.append({"line": line_number, "context": line[max(0, offset - 100):offset + len(query) + 160].strip()})
                if len(matches) >= max(1, min(limit, 100)):
                    break
        return {"tab": self.current.public(), "query": query, "matches": matches}

    def scroll(self, characters: int) -> dict[str, Any]:
        tab = self.current
        before = tab.scroll_offset
        tab.scroll_offset = max(0, min(len(tab.text), before + int(characters)))
        return {**tab.public(), "before": before, "after": tab.scroll_offset, "changed": before != tab.scroll_offset}

    def type_field(self, name: str, value: str) -> dict[str, Any]:
        inputs = [item for form in self.current.forms for item in form["inputs"] if item["name"] == name]
        if not inputs:
            raise LookupError("browser_form_field_not_found")
        if any(item["type"] in {"file", "password"} for item in inputs):
            raise ValueError("browser_field_requires_dedicated_tool")
        self.current.form_values[name] = value
        return {"tab": self.current.public(), "field": name, "characters": len(value), "value_set": True}

    def set_control(self, name: str, *, value: str = "", checked: bool | None = None) -> dict[str, Any]:
        controls = [item for form in self.current.forms for item in form["inputs"] if item.get("name") == name]
        if not controls:
            raise LookupError("browser_form_control_not_found")
        control = controls[0]
        if control.get("disabled"):
            raise ValueError("browser_form_control_disabled")
        kind = str(control.get("type", "text")).casefold()
        if kind in {"checkbox", "radio"}:
            if checked is None:
                raise ValueError("browser_checked_state_required")
            self.current.form_values[name] = str(control.get("value", "on")) if checked else ""
            control["checked"] = checked
        elif kind == "select":
            option = next((item for item in control.get("options", []) if value in {item.get("value"), item.get("label")}), None)
            if option is None:
                raise LookupError("browser_select_option_not_found")
            self.current.form_values[name] = str(option["value"])
            control["value"] = str(option["value"])
        else:
            return self.type_field(name, value)
        return {
            "tab": self.current.public(), "field": name, "type": kind,
            "value": self.current.form_values[name], "control_set": True,
        }

    def submit_form(self, *, form_index: int = 0, submit_name: str = "") -> dict[str, Any]:
        tab = self.current
        if form_index < 0 or form_index >= len(tab.forms):
            raise IndexError("browser_form_not_found")
        form = tab.forms[form_index]
        action = urllib.parse.urljoin(tab.url, form["action"] or tab.url)
        if urllib.parse.urlsplit(action).scheme != "https":
            raise ValueError("insecure_form_action_rejected")
        values = dict(tab.form_values)
        for control in form["inputs"]:
            name = str(control.get("name", ""))
            kind = str(control.get("type", ""))
            if name and name not in values and kind not in {"file", "submit", "button"}:
                values[name] = str(control.get("value", ""))
            if submit_name and name == submit_name:
                values[name] = str(control.get("value", ""))
        encoded = urllib.parse.urlencode(values).encode("utf-8")
        method = str(form.get("method", "get")).upper()
        request_url = action
        data: bytes | None = None
        if method == "GET":
            request_url += ("&" if "?" in request_url else "?") + encoded.decode("ascii")
        elif method == "POST":
            data = encoded
        else:
            raise ValueError("browser_form_method_unsupported")
        request = urllib.request.Request(
            request_url, data=data, method=method,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ARCHEON/10 Desktop BrowserAgent"},
        )
        return self._navigate_request(request)

    def _navigate_request(self, request: urllib.request.Request) -> dict[str, Any]:
        """Submit a request and parse its final page without bypassing HTTPS checks."""
        with self._opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            if urllib.parse.urlsplit(final_url).scheme.casefold() != "https":
                raise ValueError("insecure_redirect_rejected")
            raw = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(raw) > self.MAX_RESPONSE_BYTES:
                raise ValueError("browser_response_too_large")
            encoding = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(encoding, "replace")
            status = int(getattr(response, "status", 200))
        return self._apply_html(final_url, html, status, record_history=True)

    def scroll_until(
        self, query: str, *, step_characters: int = 10_000, max_steps: int = 12,
        allow_pagination: bool = True, reload_dynamic: bool = True,
    ) -> dict[str, Any]:
        needle = query.casefold().strip()
        if not needle:
            raise ValueError("browser_scroll_goal_required")
        max_steps = max(1, min(int(max_steps), 40))
        visited = {self.current.url}
        observations: list[dict[str, Any]] = []
        for step in range(max_steps + 1):
            if needle in self.current.text.casefold():
                return {"found": True, "steps": step, "tab": self.current.public(), "observations": observations}
            moved = self.scroll(step_characters)
            observations.append({"step": step, "action": "scroll", "offset": moved["after"]})
            if moved["changed"]:
                continue
            if reload_dynamic:
                refreshed = self.reload()
                observations.append({"step": step, "action": "reload", "dom_changed": refreshed["dom_changed"]})
                if refreshed["dom_changed"]:
                    continue
            if allow_pagination:
                next_link = self._next_page_link(visited)
                if next_link:
                    visited.add(next_link["url"])
                    self.navigate(next_link["url"])
                    observations.append({"step": step, "action": "next_page", "url": next_link["url"]})
                    continue
            break
        return {"found": False, "steps": len(observations), "tab": self.current.public(), "observations": observations}

    async def scroll_until_async(self, query: str, **options: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self.scroll_until, query, **options)

    def _next_page_link(self, visited: set[str]) -> dict[str, str] | None:
        labels = ("next", "siguiente", "more", "más", "load more", "ver más")
        for link in self.current.links:
            label = " ".join(link["text"].casefold().split())
            if link["url"] not in visited and any(token == label or token in label for token in labels):
                return link
        return None

    def upload(self, file_path: str | Path, *, form_index: int = 0, file_field: str = "") -> dict[str, Any]:
        tab = self.current
        if form_index < 0 or form_index >= len(tab.forms):
            raise IndexError("browser_form_not_found")
        form = tab.forms[form_index]
        file_inputs = [item for item in form["inputs"] if item["type"] == "file"]
        selected = next((item for item in file_inputs if item["name"] == file_field), None) if file_field else (file_inputs[0] if len(file_inputs) == 1 else None)
        if selected is None:
            raise LookupError("browser_file_input_ambiguous_or_missing")
        source = Path(file_path).expanduser().resolve()
        if not source.is_file() or source.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("browser_upload_file_invalid")
        boundary = f"----ARCHEON{uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in tab.form_values.items():
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{selected['name']}\"; filename=\"{source.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        )
        chunks.append(source.read_bytes()); chunks.append(f"\r\n--{boundary}--\r\n".encode())
        action = urllib.parse.urljoin(tab.url, form["action"])
        if urllib.parse.urlsplit(action).scheme != "https":
            raise ValueError("insecure_form_action_rejected")
        request = urllib.request.Request(
            action, data=b"".join(chunks), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "ARCHEON/10 Desktop BrowserAgent"},
        )
        with self._opener.open(request, timeout=30) as response:
            status = int(getattr(response, "status", 200)); final_url = response.geturl()
            response.read(self.MAX_RESPONSE_BYTES + 1)
        return {"file": str(source), "field": selected["name"], "status": status, "url": final_url, "submitted": 200 <= status < 400}

    def click_link(self, text: str) -> dict[str, Any]:
        needle = text.casefold().strip()
        exact = [item for item in self.current.links if item["text"].casefold().strip() == needle]
        candidates = exact or [item for item in self.current.links if needle in item["text"].casefold()]
        if not candidates:
            raise LookupError("browser_link_not_found")
        if len(candidates) > 1 and not exact:
            raise LookupError("browser_link_ambiguous")
        return self.navigate(candidates[0]["url"])

    def back(self) -> dict[str, Any]:
        tab = self.current
        if tab.history_index <= 0:
            raise RuntimeError("browser_no_back_history")
        tab.history_index -= 1
        return self.navigate(tab.history[tab.history_index], record_history=False)

    def forward(self) -> dict[str, Any]:
        tab = self.current
        if tab.history_index >= len(tab.history) - 1:
            raise RuntimeError("browser_no_forward_history")
        tab.history_index += 1
        return self.navigate(tab.history[tab.history_index], record_history=False)

    def new_tab(self, url: str = "") -> dict[str, Any]:
        if len(self._tabs) >= 16:
            raise RuntimeError("browser_tab_limit_reached")
        self._tabs.append(BrowserTab()); self._active = len(self._tabs) - 1
        return self.navigate(url) if url else self.current.public()

    def switch_tab(self, tab_id: str) -> dict[str, Any]:
        index = next((i for i, tab in enumerate(self._tabs) if tab.id == tab_id), None)
        if index is None:
            raise LookupError("browser_tab_not_found")
        self._active = index
        return self.current.public()

    def close_tab(self, tab_id: str = "") -> dict[str, Any]:
        if len(self._tabs) == 1:
            self._tabs[0] = BrowserTab(); self._active = 0
            return self.current.public()
        index = self._active if not tab_id else next((i for i, tab in enumerate(self._tabs) if tab.id == tab_id), -1)
        if index < 0:
            raise LookupError("browser_tab_not_found")
        self._tabs.pop(index); self._active = min(self._active, len(self._tabs) - 1)
        return self.current.public()

    def download(self, url: str, destination: str | Path) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https":
            raise ValueError("https_url_required")
        target = Path(destination).expanduser().resolve()
        if target.exists() or not target.parent.is_dir():
            raise FileExistsError("download_target_unavailable")
        request = urllib.request.Request(url, headers={"User-Agent": "ARCHEON/10 Desktop BrowserAgent"})
        partial = target.with_suffix(target.suffix + ".part")
        total = 0
        try:
            with self._opener.open(request, timeout=20) as response, partial.open("xb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 512 * 1024 * 1024:
                        raise ValueError("download_too_large")
                    output.write(chunk)
            partial.replace(target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return {"url": url, "destination": str(target), "bytes": total, "verified": target.is_file() and target.stat().st_size == total}
