from __future__ import annotations

import json
import io
import base64
import tempfile
import unittest
import urllib.error
import urllib.request
import time
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from archeon.agent import AgentStep, AgentTask, TaskStatus
from archeon.artifacts import ImageResult
from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault, Session
from archeon.auth.manager import Identity, ProviderSession
from archeon.media.providers import MediaSearchResult
from tests.test_browser_agent import FakeOpener
from archeon.ui.server import UI_ROOT


class ApplicationUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.application = ArcheonApplication(
            data_dir=data_dir,
            port=0,
            auth_provider=DevelopmentAuthProvider(data_dir / "development-auth.json"),
            auth_vault=MemorySessionVault(),
        )
        self.application.start()
        self.session_token = self.application.auth.guest().token

    def tearDown(self) -> None:
        self.application.stop()
        self.temp.cleanup()

    def request(self, path: str, *, body: dict | None = None, authorized: bool = True):
        headers = {}
        data = None
        if authorized:
            headers["X-Archeon-Token"] = self.application.ui_server.token
            headers["X-Archeon-Session"] = self.session_token
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.application.ui_server.url + path, headers=headers, data=data)
        return urllib.request.urlopen(request, timeout=2)

    def test_health_requires_runtime_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/health", authorized=False)
        self.assertEqual(caught.exception.code, 401)
        with self.request("/api/health") as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tools_loaded"], 0)

    def test_mobile_permission_states_round_trip_through_authenticated_api(self) -> None:
        with self.request(
            "/api/action",
            body={"action": "permissions.update", "permission": "desktop.observe", "state": "session"},
        ) as response:
            updated = json.load(response)
        self.assertTrue(updated["ok"])
        current = {item["id"]: item for item in updated["permissions"]}
        self.assertEqual(current["desktop.observe"]["state"], "session")

        with self.request("/api/action", body={"action": "permissions.list"}) as response:
            listed = json.load(response)
        self.assertEqual(
            {item["id"]: item["state"] for item in listed["permissions"]}["desktop.observe"],
            "session",
        )

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(
                "/api/action",
                body={"action": "permissions.update", "permission": "unknown.permission", "state": "always"},
            )
        self.assertEqual(caught.exception.code, 400)

    def test_real_command_flows_through_orchestrator(self) -> None:
        with self.request("/api/command", body={"text": "estado del sistema"}) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["data"]["logical_cpu_count"], 0)
        self.assertEqual(self.application.tools.loaded_tool_count, 1)

    def test_document_command_reads_exact_second_pdf_page_with_verified_context(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "document.pdf"
        self.application._task_context.selected_file = str(fixture.resolve())
        response = self.application.handle_command("Busca el PDF de prueba y dime qué dice la segunda página.")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "document_agent")
        self.assertEqual(response["data"]["page"], 2)
        self.assertTrue(response["data"]["verified"])
        self.assertIn("2026-ARC-042", response["message"])
        self.assertIn("Boris Saldarrega", response["message"])

    def test_multiple_text_attachments_are_routed_read_and_released(self) -> None:
        first = self.application.attachments.add_stream("uno.txt", "text/plain", 4, io.BytesIO(b"uno\n"))
        second = self.application.attachments.add_stream("dos.md", "text/markdown", 6, io.BytesIO(b"# dos\n"))
        response = self.application.handle_request("lee esto", [first.id, second.id])
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "multi_document_reader")
        self.assertEqual(len(response["data"]["file_routes"]), 2)
        self.assertTrue(response["attachments_consumed"])
        self.assertFalse(first.path.exists())
        self.assertFalse(second.path.exists())

    def test_document_followup_creates_verified_word_and_pdf(self) -> None:
        self.application._last_document_output = {
            "title": "Actividad de prueba", "content": "Contenido verificado", "source": "memory:test",
        }
        with patch("archeon.app.Path.home", return_value=Path(self.temp.name)):
            response = self.application.handle_command("hazlo en Word y también en PDF")
        self.assertTrue(response["ok"])
        self.assertEqual({item["format"] for item in response["data"]["artifacts"]}, {"docx", "pdf"})
        self.assertTrue(all(Path(item["path"]).is_file() for item in response["data"]["artifacts"]))

    def test_programming_command_repairs_controlled_project_and_preserves_user_file(self) -> None:
        project = Path(self.temp.name) / "controlled-project"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            "[project]\nname='controlled-project'\nversion='0.0.1'\n", encoding="utf-8",
        )
        source = project / "app.py"
        source.write_text(
            'def message():\n    return "ARCHI FIXED"\n\nprint(mesage())\n', encoding="utf-8",
        )
        user_file = project / "user-notes.txt"
        user_file.write_text("USER DATA MUST REMAIN", encoding="utf-8")
        self.application._task_context.active_project = str(project)
        response = self.application.handle_command("Archeon, este proyecto no inicia. Arréglalo.")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "programming_agent")
        self.assertEqual(response["data"]["exit_code"], 0)
        self.assertTrue(response["data"]["process_cleanup_verified"])
        self.assertIn("print(message())", source.read_text(encoding="utf-8"))
        self.assertEqual(user_file.read_text(encoding="utf-8"), "USER DATA MUST REMAIN")
        transcript = (
            self.application.data_dir / "memory" / "tasks" / f"{response['data']['task_id']}.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ARCHI FIXED", transcript)
        self.assertNotIn('print(message())', transcript)
        self.assertIn("<not persisted>", transcript)

    def test_stop_command_cancels_active_agent_and_terminal_tree(self) -> None:
        task = AgentTask(
            "Controlled long task",
            (AgentStep(
                "long-command", "Controlled wait", "terminal.run",
                {"command": "Start-Sleep -Seconds 10", "cwd": self.temp.name, "timeout_seconds": 20},
                "command completed", max_retries=0,
            ),),
            ("cancelled on user interruption",),
        )
        finished = []
        worker = Thread(target=lambda: finished.append(self.application.agent_runner.run(
            task, scope_permissions=frozenset({"terminal.execute"}),
        )))
        worker.start()
        for _ in range(40):
            if self.application.agent_runner.active_task_count:
                break
            time.sleep(0.025)
        response = self.application.handle_command("para")
        worker.join(timeout=8)
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "agent_cancel")
        self.assertFalse(worker.is_alive())
        self.assertEqual(finished[0].status, TaskStatus.CANCELLED)
        self.assertEqual(self.application.agent_runner.active_task_count, 0)

    def test_cancela_phrase_cancels_active_agent(self) -> None:
        task = AgentTask(
            "Controlled cancellable task",
            (AgentStep(
                "long-command", "Controlled wait", "terminal.run",
                {"command": "Start-Sleep -Seconds 10", "cwd": self.temp.name, "timeout_seconds": 20},
                "command completed", max_retries=0,
            ),),
            ("cancelled on user interruption",),
        )
        finished = []
        worker = Thread(target=lambda: finished.append(self.application.agent_runner.run(
            task, scope_permissions=frozenset({"terminal.execute"}),
        )))
        worker.start()
        for _ in range(40):
            if self.application.agent_runner.active_task_count:
                break
            time.sleep(0.025)
        response = self.application.handle_command("cancela")
        worker.join(timeout=8)
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "agent_cancel")
        self.assertFalse(worker.is_alive())
        self.assertEqual(finished[0].status, TaskStatus.CANCELLED)

    def test_agent_pause_resume_and_stop_actions_control_one_live_task(self) -> None:
        task = AgentTask(
            "Pauseable controlled task",
            (AgentStep(
                "long-command", "Controlled wait", "terminal.run",
                {"command": "Start-Sleep -Seconds 10", "cwd": self.temp.name, "timeout_seconds": 20},
                "command completed", max_retries=0,
            ),),
            ("user can interrupt",),
        )
        finished = []
        worker = Thread(target=lambda: finished.append(self.application.agent_runner.run(
            task, scope_permissions=frozenset({"terminal.execute"}),
        )))
        worker.start()
        for _ in range(80):
            if self.application.agent_runner.active_task_count:
                break
            time.sleep(0.025)
        paused = self.application.handle_action("agent.pause")
        resumed = self.application.handle_action("agent.resume")
        stopped = self.application.handle_action("agent.stop")
        worker.join(timeout=8)
        self.assertTrue(paused["ok"] and resumed["ok"] and stopped["ok"])
        self.assertFalse(worker.is_alive())
        self.assertEqual(finished[0].status, TaskStatus.CANCELLED)

    def test_browser_command_uses_official_dom_navigation_and_updates_context(self) -> None:
        pages = {
            "https://docs.python.org/3/": b"<title>Python Docs</title><p>Official Python documentation.</p>",
            "https://docs.python.org/3/search.html?q=pathlib&check_keywords=yes&area=default": b"<title>Search</title><p>pathlib result</p>",
            "https://docs.python.org/3/library/pathlib.html": b"<title>pathlib</title><h1>Object-oriented filesystem paths</h1><p>Path objects provide filesystem semantics.</p>",
        }
        self.application.browser_agent.session._opener = FakeOpener(pages)
        response = self.application.handle_command(
            "Abre el navegador y busca la documentación oficial de Python sobre pathlib."
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "browser_agent")
        self.assertEqual(response["data"]["url"], "https://docs.python.org/3/library/pathlib.html")
        self.assertTrue(response["data"]["verified"])
        self.assertEqual(self.application._task_context.current_url, response["data"]["url"])
        self.assertIn("filesystem semantics", response["message"])

    def test_music_voice_command_uses_provider_result_and_selected_output_path(self) -> None:
        result = MediaSearchResult(
            id="audius:track1", provider="audius", title="LATIN MAFIA - JULIETA (SAU REMIX)", artist="SAU",
            stream_url="https://api.audius.co/v1/tracks/track1/stream?app_name=ARCHEON",
        )
        original_search = self.application.media_discovery.search
        original_search_legacy = self.application.media_discovery.search_legacy
        original_load = self.application.media.load_results
        original_play = self.application.media.play
        loaded = []
        try:
            self.application.media_discovery.search = lambda *_args, **_kwargs: {
                "results": [result.public()], "provider": "audius",
                "online_fallback": True, "online_available": True,
            }
            self.application.media_discovery.search_legacy = lambda *_args, **_kwargs: {
                "results": [], "provider": "legacy_local", "trace": [],
            }
            self.application.media_discovery._results = {result.id: result}
            self.application.media.load_results = lambda items: loaded.extend(items) or [item.public() for item in items]
            self.application.media.play = lambda: {"state": "playing"}
            response = self.application.handle_command("reproduce julieta de latin mafia")
            self.assertTrue(response["ok"])
            self.assertTrue(response["data"]["confirmation_required"])
            self.assertIn("No encontré la versión original", response["message"])
            self.assertEqual(loaded, [])
            response = self.application.handle_command("sí")
        finally:
            self.application.media_discovery.search = original_search
            self.application.media_discovery.search_legacy = original_search_legacy
            self.application.media.load_results = original_load
            self.application.media.play = original_play
        self.assertTrue(response["ok"])
        self.assertIn("Reproduciendo LATIN MAFIA - JULIETA", response["message"])
        self.assertEqual(loaded[0].provider, "audius")

    def test_spoken_media_controls_never_fall_through_to_text_ai(self) -> None:
        original_stop = self.application.media.stop_playback
        original_pause = self.application.media.pause
        self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.PLAYING
        calls = []
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command("hola detén la canción getafe")
        finally:
            self.application.media.stop_playback = original_stop
            self.application.media.pause = original_pause
            self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.STOPPED
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "media_control")
        self.assertEqual(response["data"]["action"], "media.stop")
        self.assertEqual(calls, ["stop"])

    def test_advice_request_with_para_does_not_stop_active_media(self) -> None:
        self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.PLAYING
        original_stop = self.application.media.stop_playback
        calls = []
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command(
                "dame un consejo me ayudaron en darme una palanca para conseguir una entrevista "
                "de trabajo pero esos horarios no cuadran para mí"
            )
        finally:
            self.application.media.stop_playback = original_stop
            self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.STOPPED
        self.assertNotEqual(response.get("data", {}).get("route"), "media_control")
        self.assertEqual(calls, [])

    def test_short_para_command_still_stops_active_media(self) -> None:
        self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.PLAYING
        original_stop = self.application.media.stop_playback
        calls = []
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command("para")
        finally:
            self.application.media.stop_playback = original_stop
            self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.STOPPED
        self.assertEqual(response["data"]["action"], "media.stop")
        self.assertEqual(calls, ["stop"])

    def test_contextual_detente_stops_active_media(self) -> None:
        self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.PLAYING
        original_stop = self.application.media.stop_playback
        calls = []
        try:
            self.application.media.stop_playback = lambda: calls.append("stop") or {"state": "stopped"}
            response = self.application.handle_command("detente")
        finally:
            self.application.media.stop_playback = original_stop
            self.application.media._playback_state = __import__("archeon.media", fromlist=["MediaState"]).MediaState.STOPPED
        self.assertEqual(response["data"]["action"], "media.stop")
        self.assertEqual(calls, ["stop"])

    def test_no_mejor_reproduce_replaces_pending_song_request(self) -> None:
        alternative = MediaSearchResult(id="audius:old", provider="audius", title="Old Remix", artist="Remixer", stream_url="https://api.audius.co/v1/tracks/old/stream?app_name=ARCHEON")
        replacement = MediaSearchResult(id="audius:new", provider="audius", title="Hello Cotto", artist="Anonimo", stream_url="https://api.audius.co/v1/tracks/new/stream?app_name=ARCHEON")
        self.application._pending_media_result = {"id": alternative.id, "display": "Old Remix", "expires_at": time.monotonic()+120}
        original_search = self.application.media_discovery.search
        original_load = self.application.media.load_results
        original_play = self.application.media.play
        loaded = []
        try:
            self.application.media_discovery.search = lambda query, **_kwargs: ({"results":[replacement.public()],"provider":"audius","online_fallback":True,"online_available":True} if "hello cotto" in query.casefold() else {"results":[],"provider":None})
            self.application.media_discovery._results = {replacement.id: replacement}
            self.application.media.load_results = lambda items: loaded.extend(items) or [item.public() for item in items]
            self.application.media.play = lambda: {"state":"playing"}
            response = self.application.handle_command("no, mejor reproduce Hello Cotto de Duki")
        finally:
            self.application.media_discovery.search = original_search
            self.application.media.load_results = original_load
            self.application.media.play = original_play
        self.assertTrue(response["ok"])
        self.assertEqual(loaded[0].id, replacement.id)
        self.assertEqual(loaded[0].artist, "Duki")
        self.assertEqual(loaded[0].artist_source, "user_request_verified_title")
        self.assertIn("Hello Cotto", response["message"])

    def test_media_ui_uses_session_truth_and_restores_configured_logo(self) -> None:
        script = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        css = (UI_ROOT / "polish.css").read_text(encoding="utf-8")
        self.assertIn('postAction("media.status")', script)
        self.assertIn("renderMediaSession(mediaStatus.media)", script)
        self.assertIn("restoreUserOrbVisual", script)
        self.assertIn('visible:essentialLayoutItems.has(key)?true:item.visible!==false', script)
        self.assertNotIn(".music-widget.active,.music-widget.layout-user-visible", css)

    def test_general_settings_expose_only_wired_startup_and_performance_options(self) -> None:
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        script = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        for setting_id in (
            "settings-start-ghost", "settings-ghost-topmost",
            "settings-launch-at-login", "settings-window-mode", "auth-reset", "reset-code",
            "reset-password", "reset-password-confirm",
            "settings-performance-profile", "settings-idle-animation",
            "settings-approval-mode",
        ):
            self.assertIn(f'id="{setting_id}"', html)
            self.assertIn(setting_id, script)
        self.assertIn('approval:{mode:document.getElementById("settings-approval-mode").value}', script)

    def test_signup_otp_can_be_resumed_after_restarting_the_ui(self) -> None:
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        script = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="register-password-confirm"', html)
        self.assertIn('data-password-target="login-password"', html)
        self.assertIn('id="verify-email"', html)
        self.assertIn('pattern="[0-9]{8}"', html)
        self.assertIn('data-auth-view="verify"', html)
        self.assertIn('document.getElementById("verify-email").value.trim()', script)

    def test_recent_artist_context_repairs_bounded_stt_variant(self) -> None:
        queries = []
        original_search = self.application.media_discovery.search
        try:
            self.application.media_discovery.search = lambda query, **_kwargs: queries.append(query) or {
                "results": [], "provider": None, "online_fallback": True, "online_available": True,
            }
            self.application.handle_command("reproduce julieta de latin mafia")
            self.application.handle_command("reproduce se fue la luz de la mafia")
        finally:
            self.application.media_discovery.search = original_search
        self.assertEqual(queries[0], "julieta latin mafia")
        self.assertEqual(queries[-1], "se fue la luz latin mafia")

    def test_music_followup_stt_error_reuses_grounded_recent_query(self) -> None:
        queries = []
        original_search = self.application.media_discovery.search
        original_search_legacy = self.application.media_discovery.search_legacy
        try:
            self.application.media_discovery.search = lambda query, **_kwargs: queries.append(query) or {
                "results": [], "provider": None, "online_fallback": True, "online_available": True,
            }
            self.application.media_discovery.search_legacy = lambda query, **_kwargs: queries.append(query) or {
                "results": [], "provider": "legacy_local", "online_fallback": False,
                "online_available": False, "resolver_state": "not_found",
            }
            self.application.handle_command("reproduce imagine de john lennon")
            response = self.application.handle_command("quiero que tú la has respondido por aquí")
        finally:
            self.application.media_discovery.search = original_search
            self.application.media_discovery.search_legacy = original_search_legacy
        self.assertFalse(response["ok"])
        self.assertEqual(queries[-1], "imagine john lennon")

    def test_contextual_stt_resolves_stain_to_grounded_steam(self) -> None:
        original_command_item = self.application.launcher.command_item
        original_catalog = self.application.launcher.speech_catalog
        original_launch = self.application.launcher.launch
        launched = []
        try:
            self.application.launcher.command_item = lambda _text: None
            self.application.launcher.speech_catalog = lambda: [
                {"id": "steam", "name": "Steam", "kind": "app", "aliases": []},
            ]
            self.application.launcher.launch = lambda item_id: launched.append(item_id) or {
                "id": item_id, "name": "Steam", "accepted_by_windows": True,
            }
            response = self.application.handle_command("Archeon, abre stain")
        finally:
            self.application.launcher.command_item = original_command_item
            self.application.launcher.speech_catalog = original_catalog
            self.application.launcher.launch = original_launch
        self.assertTrue(response["ok"])
        self.assertEqual(response["message"], "Abriendo Steam")
        self.assertEqual(response["data"]["route"], "speech_context")
        self.assertEqual(launched, ["steam"])

    def test_general_question_does_not_load_launcher_catalog(self) -> None:
        original_catalog = self.application.launcher.speech_catalog
        self.application.launcher.speech_catalog = lambda: (_ for _ in ()).throw(AssertionError("unexpected launcher scan"))
        try:
            response = self.application.handle_command("Explícame qué es Docker")
        finally:
            self.application.launcher.speech_catalog = original_catalog
        self.assertIn("ok", response)

    def test_command_failure_is_contained_and_returns_a_correlation_id(self) -> None:
        original = self.application._handle_command
        self.application._handle_command = lambda _text: (_ for _ in ()).throw(RuntimeError("internal detail"))
        try:
            with self.request("/api/command", body={"text": "hola"}) as response:
                payload = json.load(response)
        finally:
            self.application._handle_command = original
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["message"], "No pude procesar esa solicitud.")
        self.assertTrue(payload["correlation_id"])
        self.assertNotIn("internal detail", json.dumps(payload))

    def test_action_failure_is_contained_without_stopping_the_server(self) -> None:
        original = self.application._handle_action
        self.application._handle_action = lambda _action, _payload=None: (_ for _ in ()).throw(RuntimeError("internal detail"))
        try:
            request = urllib.request.Request(
                self.application.ui_server.url + "/api/action",
                headers={
                    "X-Archeon-Token": self.application.ui_server.token,
                    "X-Archeon-Session": self.session_token,
                    "Content-Type": "application/json",
                },
                data=json.dumps({"action": "voice.catalog"}).encode(),
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            payload = json.load(caught.exception)
        finally:
            self.application._handle_action = original
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(payload["error"], "action_failed")
        self.assertTrue(payload["correlation_id"])
        with self.request("/api/health") as response:
            self.assertTrue(json.load(response)["ok"])

    def test_one_hundred_text_commands_do_not_stop_the_local_server(self) -> None:
        for index in range(100):
            with self.request("/api/command", body={"text": f"mensaje {index}"}) as response:
                self.assertIn("ok", json.load(response))
        with self.request("/api/health") as response:
            self.assertTrue(json.load(response)["ok"])

    def test_attachment_upload_streams_into_request_context_and_is_released(self) -> None:
        body = b"print('hola')\n"
        request = urllib.request.Request(
            self.application.ui_server.url + "/api/attachment?name=main.py",
            headers={
                "X-Archeon-Token": self.application.ui_server.token,
                "X-Archeon-Session": self.session_token,
                "Content-Type": "text/x-python",
            },
            data=body,
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            uploaded = json.load(response)
        attachment = uploaded["attachment"]
        self.assertEqual(attachment["kind"], "code")
        with self.request(
            "/api/command",
            body={"text": "estado del sistema", "attachments": [attachment["id"]]},
        ) as response:
            result = json.load(response)
        self.assertTrue(result["ok"])
        self.assertTrue(result["attachments_consumed"])
        self.assertEqual(result["request_context"]["attachments"][0]["name"], "main.py")
        self.assertFalse(any(path.is_file() for path in (Path(self.temp.name) / "attachments" / "pending").rglob("*")))

    def test_commands_require_an_application_session(self) -> None:
        request = urllib.request.Request(
            self.application.ui_server.url + "/api/command",
            headers={"X-Archeon-Token": self.application.ui_server.token, "Content-Type": "application/json"},
            data=json.dumps({"text": "estado del sistema"}).encode(),
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 401)

    def test_window_action_is_persisted_and_published(self) -> None:
        subscription = self.application.events.subscribe("ui.window.*")
        with self.request("/api/action", body={"action": "window.ghost"}) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertTrue(self.application.configuration.config.ghost.enabled)
        self.assertEqual(subscription.get(timeout=0.2).type, "ui.window.ghost")
        subscription.close()

    def test_settings_actions_are_real_and_emit_changes(self) -> None:
        subscription = self.application.events.subscribe("settings.changed")
        with self.request("/api/action", body={"action": "settings.get"}) as response:
            current = json.load(response)
        self.assertFalse(current["settings"]["startup"]["startup_sound"])
        self.assertEqual(current["paths"]["model_dir"], str(Path(self.temp.name) / "models"))
        with self.request(
            "/api/action",
            body={"action": "settings.update", "changes": {"assistant": {"wake_name": "Nova"}}},
        ) as response:
            updated = json.load(response)
        self.assertEqual(updated["settings"]["assistant"]["wake_name"], "Nova")
        self.assertEqual(subscription.get(timeout=0.2).payload["sections"], ["assistant"])
        subscription.close()

    def test_settings_save_survives_optional_runtime_side_effect_failure(self) -> None:
        with patch.object(self.application.voice, "sync_wake_word", side_effect=RuntimeError("device busy")):
            result = self.application.handle_action(
                "settings.update", {"changes": {"appearance": {"accent_color": "#A855F7"}}}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["settings"]["appearance"]["accent_color"], "#A855F7")
        self.assertIn("wake_word_sync", result["warnings"])
        self.assertEqual(self.application.configuration.config.appearance.accent_color, "#A855F7")

    def test_visual_selection_is_transactional_until_settings_are_saved(self) -> None:
        logo = Path(self.temp.name) / "draft-logo.png"
        logo.write_bytes(b"draft visual")
        self.assertIsNone(self.application.configuration.config.appearance.logo_path)

        with patch("archeon.ui.native_dialogs.choose_visual_file", return_value=str(logo)):
            with self.request(
                "/api/action", body={"action": "appearance.choose", "kind": "logo"},
            ) as response:
                draft = json.load(response)
        self.assertTrue(draft["ok"])
        self.assertEqual(draft["settings"]["appearance"]["logo_path"], str(logo))
        self.assertIsNone(self.application.configuration.config.appearance.logo_path)

        with self.request("/api/action", body={"action": "appearance.discard"}) as response:
            self.assertTrue(json.load(response)["ok"])
        self.assertIsNone(self.application.configuration.config.appearance.logo_path)

        with patch("archeon.ui.native_dialogs.choose_visual_file", return_value=str(logo)):
            with self.request(
                "/api/action", body={"action": "appearance.choose", "kind": "logo"},
            ) as response:
                self.assertTrue(json.load(response)["ok"])
        with self.request(
            "/api/action",
            body={"action": "settings.update", "changes": {"appearance": {"logo_zoom": 125}}},
        ) as response:
            saved = json.load(response)
        self.assertTrue(saved["ok"])
        self.assertEqual(self.application.configuration.config.appearance.logo_path, str(logo))
        self.assertEqual(self.application.configuration.config.appearance.logo_zoom, 125)

    def test_chat_background_is_transactional_and_can_be_cleared_independently(self) -> None:
        chat = Path(self.temp.name) / "chat-background.png"
        chat.write_bytes(b"chat visual")
        with patch("archeon.ui.native_dialogs.choose_visual_file", return_value=str(chat)):
            chosen = self.application.handle_action("appearance.choose", {"kind": "chat"})
        self.assertTrue(chosen["ok"])
        self.assertEqual(chosen["settings"]["appearance"]["chat_background_path"], str(chat))
        self.assertIsNone(self.application.configuration.config.appearance.chat_background_path)
        saved = self.application.handle_action("settings.update", {"changes": {"appearance": {}}})
        self.assertTrue(saved["ok"])
        self.assertEqual(self.application.configuration.config.appearance.chat_background_path, str(chat))
        cleared = self.application.handle_action("appearance.clear", {"kind": "chat"})
        self.assertTrue(cleared["ok"])
        self.assertIsNone(cleared["settings"]["appearance"]["chat_background_path"])
        self.assertEqual(self.application.configuration.config.appearance.chat_background_path, str(chat))

    def test_accessible_listening_pause_blocks_voice_commands_until_resume_phrase(self) -> None:
        paused = self.application.handle_command("deja de escuchar")
        self.assertTrue(paused["ok"])
        self.assertTrue(self.application.configuration.config.assistant.listening_paused)
        ignored = self.application._handle_voice_command("abre la calculadora")
        self.assertTrue(ignored["data"]["ignored"])
        resumed = self.application._handle_voice_command("vuelve a escuchar")
        self.assertTrue(resumed["ok"])
        self.assertFalse(self.application.configuration.config.assistant.listening_paused)

    def test_model_directory_change_is_persisted_and_used_by_voice(self) -> None:
        selected = Path(self.temp.name) / "external-model-storage"
        with self.request(
            "/api/action",
            body={"action": "settings.update", "changes": {"storage": {"model_dir": str(selected)}}},
        ) as response:
            updated = json.load(response)
        self.assertTrue(updated["ok"])
        self.assertEqual(updated["settings"]["storage"]["model_dir"], str(selected))
        self.assertEqual(self.application.voice._models_root(), selected)
        self.assertTrue(selected.is_dir())

    def test_command_input_visibility_can_be_changed_by_voice_command(self) -> None:
        hidden = self.application.handle_command("oculta la barra de comandos")
        self.assertTrue(hidden["ok"])
        self.assertFalse(self.application.configuration.config.appearance.command_input_visible)
        shown = self.application.handle_command("show command bar")
        self.assertTrue(shown["ok"])
        self.assertTrue(self.application.configuration.config.appearance.command_input_visible)

    def test_microphone_test_action_starts_without_loading_stt(self) -> None:
        original = self.application.voice.test_input
        captured = {}
        self.application.voice.test_input = lambda duration: captured.setdefault("duration", duration) is not None
        try:
            result = self.application.handle_action("audio.test_input", {"duration_seconds": 2})
        finally:
            self.application.voice.test_input = original
        self.assertTrue(result["ok"])
        self.assertEqual(captured["duration"], 2.0)

    def test_sync_action_uses_authenticated_session_without_exposing_provider_token(self) -> None:
        account = self.application.auth._create(
            ProviderSession(
                Identity("11111111-1111-1111-1111-111111111111", "owner@example.test", "Owner"),
                "provider-jwt", "provider-refresh", int(time.time()) + 3600, True,
            ),
            "account",
        )
        self.session_token = account.token
        captured = {}

        class FakeSync:
            def synchronize(_self, user_id, access_token, account_value, device_value):
                captured.update(user_id=user_id, access_token=access_token)
                return {
                    "ok": True, "queued": False, "status": "synchronized",
                    "account": account_value, "device": device_value,
                    "actions": {"account": "uploaded", "device": "uploaded"},
                }

        self.application.settings_sync = FakeSync()
        with self.request("/api/action", body={"action": "sync.now", "_session_token": "spoofed"}) as response:
            result = json.load(response)
        self.assertTrue(result["ok"])
        self.assertEqual(captured["user_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(captured["access_token"], "provider-jwt")
        self.assertNotIn("provider-jwt", json.dumps(result))

    def test_ghost_transition_resumes_session_once_in_memory(self) -> None:
        with self.request("/api/action", body={"action": "window.ghost"}) as response:
            self.assertTrue(json.load(response)["ok"])
        runtime_url = self.application.ui_server.url + "/runtime-config.js?token=" + self.application.ui_server.token
        with urllib.request.urlopen(runtime_url, timeout=2) as response:
            first = response.read().decode("utf-8")
        with urllib.request.urlopen(runtime_url, timeout=2) as response:
            second = response.read().decode("utf-8")
        self.assertIn(self.session_token, first)
        self.assertNotIn(self.session_token, second)

    def test_runtime_token_cannot_be_read_without_the_bootstrap_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.application.ui_server.url + "/runtime-config.js", timeout=2)
        self.assertEqual(raised.exception.code, 401)
        runtime_url = self.application.ui_server.url + "/runtime-config.js?token=" + self.application.ui_server.token
        with urllib.request.urlopen(runtime_url, timeout=2) as response:
            self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
            policy = response.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("script-src 'self' https://www.youtube.com", policy)

    def test_archi_image_routes_multilingual_requests_to_injected_provider(self) -> None:
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAP0lEQVR4nO3PQQ0AIBDAsAP/nuGNAvZoFSzZOjNnyNi1dgXQBaALQBcALgBdALoAdAHoAtAFoAtAF4AuAF0AugB0AegC0AWgC0AXgC4AXQC6AHQB6ALQBaALQBeALgBdALoAdAHoAtAFoAtAF4AuAF0AuvfAAWlYGbZHAAAAAElFTkSuQmCC")
        prompts = []

        class FakeImageProvider:
            def generate(_self, request):
                from PIL import Image

                prompts.append(request.prompt)
                request.output_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (request.width, request.height), "#21618C").save(request.output_path, "PNG")
                return ImageResult(
                    True, "fake", "unloaded", str(request.output_path),
                    request.width, request.height, "digest", 1.0,
                )

        self.application.image_provider = FakeImageProvider()
        requests = (
            "crea una imagen de un orbe azul", "create an image of a blue orb",
            "crie uma imagem de um orbe azul", "crée une image d'un orbe bleu",
            "erstelle ein bild von einer blauen kugel", "crea un'immagine di una sfera blu",
            "生成一张蓝色球体图片", "画像を生成 青い球体", "이미지를 생성 파란 구체",
            "создай изображение синей сферы", "أنشئ صورة كرة زرقاء", "छवि बनाओ नीला गोला",
        )
        for request in requests:
            response = self.application.handle_command(request)
            self.assertTrue(response["ok"], request)
            self.assertEqual(response["data"]["route"], "archi_image")
        self.assertEqual(len(prompts), 12)

    def test_dictation_action_transcribes_without_executing_command(self) -> None:
        with patch.object(self.application.voice, "start_dictation", return_value=True) as start:
            with self.request("/api/action", body={"action": "voice.dictation"}) as response:
                value = json.load(response)
        self.assertTrue(value["ok"])
        start.assert_called_once_with()

    def test_current_news_uses_clean_query_and_bounded_fallback(self) -> None:
        calls = []
        def search(query, **kwargs):
            calls.append((query, kwargs["freshness"]))
            return [] if kwargs["freshness"] == "pd" else [{"title": "GTA 6 update", "source": "Example", "published": "today", "url": "https://example.test/news"}]
        with patch.object(self.application.search, "search", side_effect=search):
            response = self.application.handle_command("dime la última noticia de GTA 6 y el hacker leak hoy")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "live_search")
        self.assertEqual(calls, [("gta 6 y el hacker leak", "pd"), ("gta 6 y el hacker leak", "pw")])

    def test_named_hacker_leak_question_uses_verified_live_search(self) -> None:
        calls: list[str] = []
        result = [{"title": "Verified report", "source": "Example", "published": "today", "url": "https://example.test/report"}]
        with patch.object(
            self.application.search, "search",
            side_effect=lambda query, **_kwargs: calls.append(query) or result,
        ):
            response = self.application.handle_command("oye que sabes del hacker Leek con lo del GTA 6")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["route"], "live_search")
        self.assertEqual(calls, ["hacker leek con lo del gta 6"])

    def test_ui_uses_events_not_polling(self) -> None:
        javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("EventSource", javascript)
        self.assertNotIn("setInterval", javascript)
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<audio", html)
        self.assertTrue((UI_ROOT / "locales" / "es.json").is_file())
        self.assertTrue((UI_ROOT / "locales" / "en.json").is_file())
        for locale in ("es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi"):
            catalog = json.loads((UI_ROOT / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
            self.assertIn("settings.title", catalog)

    def test_ui_assets_cannot_mix_versions_from_browser_cache(self) -> None:
        with self.request("/app.js") as response:
            response.read()
            self.assertEqual(response.headers["Cache-Control"], "no-cache, must-revalidate")

    def test_polished_ui_is_served_as_a_lightweight_layout_layer(self) -> None:
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('href="/polish.css"', html)
        self.assertLess(html.index('id="music-panel"'), html.index('class="command-console"'))
        stylesheet = (UI_ROOT / "polish.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-areas", stylesheet)
        self.assertIn(".music-widget.active", stylesheet)
        self.assertIn(".ui-hidden .ring", stylesheet)
        self.assertIn(".app-shell.input-hidden", stylesheet)
        self.assertIn('id="command-toggle"', html)
        self.assertIn('id="command-dictate"', html)
        self.assertIn('"voice.dictation"', javascript)
        self.assertIn('"speech.dictation.completed"', javascript)
        self.assertIn('id="settings-search"', html)
        self.assertIn('class="settings-center"', html)
        self.assertIn('data-settings-section="personalization"', html)
        self.assertIn('data-settings-section="accessibility"', html)
        self.assertIn('id="settings-large-targets"', html)
        self.assertIn('id="settings-left-handed"', html)
        self.assertIn('id="settings-visual-voice-cues"', html)
        self.assertIn('id="settings-pause-listening-phrase"', html)
        self.assertIn('id="settings-resume-listening-phrase"', html)
        self.assertIn('data-settings-section="music"', html)
        self.assertIn('id="settings-media-alternatives"', html)
        self.assertIn('id="settings-media-volume"', html)
        self.assertIn('id="settings-media-dj"', html)
        self.assertNotIn('id="settings-media-extended-local"', html)
        self.assertIn("La búsqueda multimedia ampliada está integrada en ARCHEON", html)
        self.assertIn('Tema, colores, accesibilidad, logo, fondo y reloj.', html)
        self.assertIn('id="background-card-title"', html)
        self.assertIn('id="logo-card-title"', html)
        self.assertIn('class="account-only session-settings"', html)
        self.assertIn('class="guest-only session-settings"', html)
        self.assertIn('id="crop-dialog"', html)
        self.assertIn('id="crop-zoom"', html)
        self.assertIn('id="core-logo-video"', html)
        self.assertIn('id="settings-confirm-dialog"', html)
        self.assertIn('id="settings-edit-layout"', html)
        self.assertIn('id="layout-editor"', html)
        self.assertIn('id="layout-confirm-dialog"', html)
        self.assertIn('data-layout-key="clock"', html)
        self.assertIn('id="settings-clock-preview"', html)
        self.assertIn('data-layout-key="session_badge"', html)
        self.assertIn('data-layout-key="command_toggle"', html)
        self.assertIn('data-layout-key="ghost_toggle"', html)
        self.assertIn('data-layout-key="menu_toggle"', html)
        self.assertIn('data-layout-key="orb"', html)
        self.assertIn('data-layout-key="assistant_name"', html)
        self.assertIn('data-layout-key="assistant_detail"', html)
        self.assertIn('data-layout-key="voice_button"', html)
        self.assertIn('data-layout-key="conversation"', html)
        self.assertIn('data-layout-key="command"', html)
        self.assertIn('id="layout-editor-scale"', html)
        self.assertIn('id="layout-editor-width"', html)
        self.assertIn('id="layout-editor-background"', html)
        self.assertIn('id="layout-editor-text"', html)
        self.assertIn('id="layout-editor-style"', html)
        self.assertIn('id="layout-editor-chat-image"', html)
        self.assertIn('id="conversation-stack"', html)
        self.assertIn('id="command-stack"', html)
        self.assertIn('id="music-choose"', html)
        self.assertIn('id="youtube-player-dialog"', html)
        self.assertIn('id="youtube-player"', html)
        self.assertIn('Los cambios realizados no se aplicarán', html)
        self.assertIn('openCropEditor("logo")', javascript)
        self.assertIn('showSettingsConfirmation("discard")', javascript)
        self.assertIn('showSettingsConfirmation("save")', javascript)
        self.assertIn('showLayoutConfirmation("discard")', javascript)
        self.assertIn('showLayoutConfirmation("reset")', javascript)
        self.assertIn('interface_layout:normalizeInterfaceLayout', javascript)
        self.assertIn('resizableLayoutItems', javascript)
        self.assertIn('URL.createObjectURL(file)', javascript)
        self.assertIn('URL.revokeObjectURL', javascript)
        self.assertIn('--layout-background', javascript)
        self.assertIn('--layout-text', javascript)
        self.assertNotIn('/layoutDrag.zoom', javascript)
        self.assertIn('"voice.pause_listening"', javascript)
        self.assertIn('"voice.resume_listening"', javascript)
        self.assertIn('getBoundingClientRect()', javascript)
        self.assertIn('input.value="";input.style.height="";', javascript)
        self.assertIn('hour12:!clock.use_24_hour', javascript)
        self.assertIn('preview.replaceChildren(timeNode,dateNode)', javascript)
        self.assertIn('function previewSettingsControls()', javascript)
        self.assertIn('"settings-clock-24h","settings-clock-seconds"', javascript)
        self.assertIn('function scheduleClock()', javascript)
        self.assertIn('clearTimeout(clockTimer)', javascript)
        self.assertIn('logoVideo.dataset.active', javascript)
        self.assertNotIn('data-settings-section="appearance"', html)
        self.assertIn('id="guest-account-cta"', html)
        self.assertIn('id="context-reply"', html)
        self.assertIn('id="agent-control"', html)
        self.assertIn('id="agent-pause"', html)
        self.assertIn('id="agent-stop"', html)
        self.assertIn('id="agent-preview"', html)
        self.assertIn('id="agent-method"', html)
        self.assertIn('id="speaker-verification-enabled"', html)
        self.assertIn('id="speaker-profiles"', html)
        self.assertIn('src="/runtime-loader.js"', html)
        self.assertNotIn('src="/runtime-config.js"', html)
        self.assertIn('"agent.pause"', javascript)
        self.assertIn('"agent.visual.updated"', javascript)
        self.assertIn('"voice.speaker.enroll"', javascript)
        self.assertIn('"media.web_state"', javascript)
        self.assertIn('"music.web.requested"', javascript)
        self.assertIn('document.body.classList.contains("state-paused")?"media.resume":"media.play"', javascript)
        self.assertIn('addEventListener("input",applyMediaVolume)', javascript)
        self.assertNotIn('id="settings-media-extended-resolver"', html)
        self.assertIn('https://www.youtube.com/iframe_api', javascript)
        mobile_html = (UI_ROOT / "mobile.html").read_text(encoding="utf-8")
        mobile_js = (UI_ROOT / "mobile.js").read_text(encoding="utf-8")
        self.assertIn('id="mobile-conversations"', mobile_html)
        self.assertIn('id="mobile-files"', mobile_html)
        self.assertIn('id="mobile-devices"', mobile_html)
        self.assertIn('id="mobile-boot"', mobile_html)
        self.assertIn('id="mobile-permissions-panel"', mobile_html)
        self.assertIn('id="mobile-browser-permissions"', mobile_html)
        self.assertIn('id="mobile-app-permissions"', mobile_html)
        self.assertIn('href="/mobile-fixes.css"', mobile_html)
        for attachment_kind in ("image", "video", "file", "camera"):
            self.assertIn(f'data-mobile-attachment="{attachment_kind}"', mobile_html)
        self.assertIn('id="mobile-accent"', mobile_html)
        self.assertIn('id="mobile-background-file"', mobile_html)
        self.assertIn('id="mobile-settings"', mobile_html)
        self.assertIn('id="mobile-settings-open"', mobile_html)
        self.assertIn('id="mobile-intelligence"', mobile_html)
        self.assertIn('id="mobile-composer-intelligence"', mobile_html)
        self.assertIn('id="mobile-dictate"', mobile_html)
        self.assertIn('id="mobile-primary-action"', mobile_html)
        self.assertIn('id="mobile-tour"', mobile_html)
        self.assertIn("display: none !important", (UI_ROOT / "mobile-fixes.css").read_text(encoding="utf-8"))
        self.assertIn('"cloud.conversations.list"', mobile_js)
        self.assertIn('"cloud.files.list"', mobile_js)
        self.assertIn('"cloud.devices.list"', mobile_js)
        self.assertIn('"permissions.list"', mobile_js)
        self.assertIn('"permissions.update"', mobile_js)
        self.assertIn('navigator.mediaDevices.getUserMedia', mobile_js)
        self.assertIn('/api/cloud-file?', mobile_js)
        self.assertIn('/api/attachment?', mobile_js)
        self.assertIn('attachments:sentAttachments.map', mobile_js)
        self.assertIn('attachmentPreviewCache', mobile_js)
        self.assertIn('result.attachments_consumed===true', mobile_js)
        self.assertIn('discardComposerAttachments', mobile_js)
        self.assertIn('renderEmptyChat()', mobile_js)
        self.assertIn('intelligenceProfiles=', mobile_js)
        self.assertIn('native.startSpeech(mode,document.documentElement.lang||"es")', mobile_js)
        self.assertIn('archeon_mobile_onboarding_completed', mobile_js)
        self.assertIn('localStorage.setItem("archeon_mobile_accent"', mobile_js)
        self.assertIn('localStorage.setItem("archeon_mobile_background"', mobile_js)
        self.assertIn('startupChatPending=true', mobile_js)
        self.assertIn('if(startupChatPending){createLocalChat({pruneEmpty:true});startupChatPending=false;}', mobile_js)
        self.assertIn('function backgroundGeometry(viewWidth,viewHeight)', mobile_js)
        self.assertIn('const ratio=backgroundFrame.clientWidth/backgroundFrame.clientHeight', mobile_js)
        self.assertIn('if(command){toast(`${spokenName} activado.`);await runSpokenCommand(command);}', mobile_js)
        self.assertIn('if(native.ensureAudibleVolume)native.ensureAudibleVolume()', mobile_js)
        for locale in ("es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi"):
            self.assertIn(f'{locale}:{{appearance:', mobile_js)
        self.assertIn('id="cloud-open"', html)
        self.assertIn('id="cloud-dialog"', html)
        self.assertIn('"cloud.files.list"', javascript)
        self.assertIn("renderAssistantText(result,value.message)", javascript)
        self.assertIn("appendInlineMarkup", javascript)
        self.assertIn('document.createElement("strong")', javascript)
        self.assertIn('document.createElement("code")', javascript)
        self.assertIn('rel="noopener noreferrer"', javascript)
        self.assertIn("object-fit:cover", stylesheet)
        with self.request("/polish.css") as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.headers["Content-Type"], "text/css")
            self.assertIn("ARCHEON UI 2.0", body)

    def test_settings_statuses_and_brand_are_localized(self) -> None:
        catalog = json.loads((UI_ROOT / "locales" / "settings.json").read_text(encoding="utf-8"))
        details = json.loads((UI_ROOT / "locales" / "settings-details.json").read_text(encoding="utf-8"))
        required = {
            "service.settings_sync", "service.signature_verifier", "service.current_version",
            "status.working", "status.configured_on_demand", "status.not_configured",
            "status.deferred", "status.blocked_by_external_infrastructure", "status.not_started",
        }
        self.assertEqual(set(catalog), {"es", "en", "pt", "fr", "de", "it", "zh", "ja", "ko", "ru", "ar", "hi"})
        for locale, translations in catalog.items():
            self.assertTrue(required.issubset(translations), locale)
        detail_required = {
            "settings.search", "personalization.reset_prompt", "accessibility.title",
            "accessibility.shortcut_note", "privacy.title", "privacy.guest_note",
            "voice.audio_input", "voice.preview_current", "voice.authorized",
            "voice.authorized_only", "voice.enroll_note", "voice.security_note",
        }
        for locale in set(catalog) - {"es", "en"}:
            self.assertTrue(detail_required.issubset(details[locale]), locale)
        javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("localizeStatus", javascript)
        self.assertIn("localizeStaticBrand", javascript)
        self.assertNotIn("Pregúntale a ChatGPT", javascript + html)

    def test_music_events_are_real_actions(self) -> None:
        subscription = self.application.events.subscribe("music.volume.changed")
        with self.request("/api/action", body={"action": "media.volume", "volume": 0.35}) as response:
            self.assertTrue(json.load(response)["ok"])
        event = subscription.get(timeout=0.2)
        self.assertEqual(event.type, "music.volume.changed")
        self.assertEqual(event.payload["volume"], 0.35)
        subscription.close()

    def test_voice_configuration_is_validated_and_persisted(self) -> None:
        catalog = {
            "profiles": ["eco", "balanced", "performance"],
            "input_devices": [{"index": 28, "name": "Shared microphone"}],
            "tts_voices": [{"id": "voice-es", "name": "Spanish voice"}],
            "tts_outputs": [{"id": "output-1", "name": "Speakers"}],
            "status": self.application.voice.status(),
        }
        original_catalog = self.application.voice.catalog
        self.application.voice.catalog = lambda: catalog
        try:
            with self.request(
                "/api/action",
                body={
                    "action": "voice.configure",
                    "profile": "balanced",
                    "input_device_id": "28",
                    "tts_voice_id": "voice-es",
                    "tts_output_device_id": "output-1",
                    "tts_style": "deep_tech",
                    "tts_rate": 2,
                    "tts_volume": 72,
                    "barge_in": False,
                },
            ) as response:
                payload = json.load(response)
        finally:
            self.application.voice.catalog = original_catalog
        self.assertTrue(payload["ok"])
        config = json.loads((Path(self.temp.name) / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["voice"]["profile"], "balanced")
        self.assertEqual(config["audio"]["input_device_id"], "28")
        self.assertEqual(config["voice"]["tts_output_device_id"], "output-1")
        self.assertEqual(config["voice"]["tts_style"], "deep")
        self.assertFalse(config["voice"]["barge_in"])

    def test_guest_session_is_local_and_logout_invalidates_it(self) -> None:
        with self.request("/api/auth/guest", body={}) as response:
            created = json.load(response)
        self.assertTrue(created["ok"])
        self.assertEqual(created["session"]["mode"], "guest")
        session_token = created["session_token"]
        request = urllib.request.Request(
            self.application.ui_server.url + "/api/session",
            headers={
                "X-Archeon-Token": self.application.ui_server.token,
                "X-Archeon-Session": session_token,
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertTrue(json.load(response)["ok"])

    def test_development_register_and_login_flow(self) -> None:
        account = {"email": "test@example.com", "password": "correct-horse", "confirm_password": "correct-horse", "display_name": "Test"}
        with self.request("/api/auth/register", body=account) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request(
            "/api/auth/login", body={"email": account["email"], "password": account["password"]}
        ) as response:
            logged_in = json.load(response)
        self.assertTrue(logged_in["ok"])
        self.assertEqual(logged_in["session"]["identity"]["display_name"], "Test")

    def test_pending_signup_never_exposes_a_local_session_token(self) -> None:
        class PendingAuth:
            def __init__(self):
                self.logged_out = None

            def register(self, email, password, display_name, locale="es"):
                return Session(
                    "temporary-local-token",
                    Identity("pending-user", email, display_name),
                    "account",
                    False,
                    True,
                )

            def logout(self, token):
                self.logged_out = token
                return True

        original = self.application.auth
        pending = PendingAuth()
        self.application.auth = pending
        try:
            result = self.application.handle_auth(
                "register",
                {
                    "email": "pending@example.com",
                    "password": "correct-horse",
                    "confirm_password": "correct-horse",
                    "display_name": "Pending",
                },
                "",
            )
        finally:
            self.application.auth = original
        self.assertTrue(result["ok"])
        self.assertTrue(result["session"]["pending_confirmation"])
        self.assertNotIn("session_token", result)
        self.assertEqual(pending.logged_out, "temporary-local-token")

    def test_server_stops_its_thread(self) -> None:
        self.assertTrue(self.application.ui_server.thread_alive)
        self.application.stop()
        self.assertFalse(self.application.ui_server.thread_alive)

    def test_personalization_video_supports_bounded_range_streaming(self) -> None:
        video = Path(self.temp.name) / "background.mp4"
        video.write_bytes(b"0123456789")
        self.application.configuration.update_settings(
            {"appearance": {"background_type": "video", "background_path": str(video)}}
        )
        request = urllib.request.Request(
            self.application.ui_server.url + "/personalization/background",
            headers={"X-Archeon-Token": self.application.ui_server.token, "Range": "bytes=2-5"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")


if __name__ == "__main__":
    unittest.main()
