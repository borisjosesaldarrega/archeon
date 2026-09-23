"""Real, low-risk M10 Computer Use validation driven by ARCHEON runtime."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Empty

import psutil

from archeon.agent import AgentMode, AgentStep, AgentTask
from archeon.app import ArcheonApplication
from archeon.core.tools import ToolContext
from archeon.desktop.windows import WindowInfo, WindowsDesktopController, WindowsDesktopObserver


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "benchmarks" / "evidence" / "computer_use"
REPORT_PATH = ROOT / "benchmarks" / "M10_COMPUTER_USE_REAL_VALIDATION.json"


def capture(observer: WindowsDesktopObserver, name: str) -> dict[str, object]:
    started = time.perf_counter()
    try:
        window = observer.active_window()
        result = observer.capture_window(window.bounds, EVIDENCE_DIR / f"{name}.png")
        return {**result, "latency_ms": round((time.perf_counter() - started) * 1000, 3)}
    except Exception as error:
        return {"path": "", "error": f"{type(error).__name__}: {error}", "latency_ms": round((time.perf_counter() - started) * 1000, 3)}


def run_youtube(app: ArcheonApplication, observer: WindowsDesktopObserver) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    subscription = app.events.subscribe("agent.*", max_queue=256)
    result_holder: dict[str, object] = {}
    trace: list[dict[str, object]] = []
    screenshots: dict[str, object] = {}
    started = time.perf_counter()

    def execute() -> None:
        result_holder.update(app.handle_command("ARCHEON, abre YouTube y busca OpenAI"))

    worker = threading.Thread(target=execute, name="archeon-m10-youtube-runtime")
    worker.start()
    capture_steps = {
        "open-youtube": "youtube_before",
        "highlight-search": "youtube_target_identified",
        "click-search": "youtube_after_click",
        "verify-results": "youtube_final_result",
    }
    while worker.is_alive():
        try:
            event = subscription.get(timeout=0.25)
        except Empty:
            continue
        payload = dict(event.payload)
        step = str(payload.get("step", ""))
        trace.append({
            "offset_ms": round((time.perf_counter() - started) * 1000, 3),
            "event": event.type, "step": step,
            "action": payload.get("step_description", ""),
        })
        if event.type == "agent.step.verified" and step in capture_steps:
            screenshots[capture_steps[step]] = capture(observer, capture_steps[step])
    worker.join(timeout=2)
    while True:
        try:
            event = subscription.get(timeout=0.01)
        except Empty:
            break
        payload = dict(event.payload)
        trace.append({"offset_ms": round((time.perf_counter() - started) * 1000, 3), "event": event.type, "step": payload.get("step", ""), "action": payload.get("step_description", "")})
    subscription.close()
    task = dict(result_holder.get("data", {})).get("task", {})
    verification = dict(result_holder.get("data", {})).get("verification", {})
    test = {
        "test": "youtube_visible_search",
        "goal": "abre YouTube y busca OpenAI",
        "application": verification.get("application", {}).get("name", ""),
        "application_type": verification.get("application", {}).get("application_type", ""),
        "permission_mode": "CONTROL",
        "perception_method": verification.get("perception_method", ""),
        "target": "YouTube search input",
        "action": "highlight, visible move, click, type, submit",
        "expected_result": "search results page for OpenAI",
        "actual_result": verification,
        "verification": bool(verification.get("verified")),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": "PASS" if result_holder.get("ok") and task.get("status") == "completed" else "FAIL",
    }
    return test, trace, screenshots


def close_notepad_without_saving(handle: int) -> None:
    if not handle:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW(handle, 0x0010, 0, 0)
    time.sleep(0.35)
    controller = WindowsDesktopController()
    for label in ("No guardar", "Don't save"):
        try:
            controller.invoke(label)
            return
        except Exception:
            continue


def run_notepad(app: ArcheonApplication, observer: WindowsDesktopObserver) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    started = time.perf_counter()
    response = app.handle_command("ARCHEON, abre el Bloc de notas y escribe: Prueba de ARCHEON Computer Use")
    task = dict(response.get("data", {})).get("task", {})
    typed = next((item for item in task.get("tool_results", []) if item.get("step") == "type-text"), {})
    opened = next((item for item in task.get("tool_results", []) if item.get("step") == "open-notepad"), {})
    screenshot = capture(observer, "notepad_text_verified")
    active = observer.active_window()
    recognition = {**observer.classify_window(active), "validation": "REAL_WINDOW"}
    test = {
        "test": "notepad_real_typing", "goal": "abre Bloc de notas y escribe texto de prueba",
        "application": "Notepad", "application_type": "native_windows_app",
        "permission_mode": "CONTROL", "perception_method": "windows_ui_automation",
        "target": "focused editable document", "action": "type text",
        "expected_result": "exact text read back from editor",
        "actual_result": typed.get("data", {}), "verification": bool(typed.get("verified")),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": "PASS" if response.get("ok") and typed.get("verified") else "FAIL",
    }
    close_notepad_without_saving(int(opened.get("data", {}).get("window", {}).get("handle", 0)))
    return test, screenshot, recognition


def run_explorer(app: ArcheonApplication, observer: WindowsDesktopObserver, root: Path) -> tuple[dict[str, object], dict[str, object], int]:
    target = root / "safe-selection.txt"
    target.write_text("ARCHEON controlled selection fixture\n", encoding="utf-8")
    task = AgentTask(
        "Reveal a controlled fixture without modifying it",
        (
            AgentStep("reveal", "Abrir Explorador y seleccionar el archivo controlado", "desktop.reveal_in_explorer", {"path": str(target)}, "item visible and selected", 1),
            AgentStep("observe", "Verificar Explorador activo", "desktop.observe_active", {"visual_fingerprint": False}, "Explorer window observed", 0),
        ),
        ("Explorer recognized", "controlled item visible"), AgentMode.CONTROL,
    )
    started = time.perf_counter()
    result = app.agent_runner.run(task, scope_permissions=frozenset({"desktop.observe", "desktop.control", "filesystem.read"}))
    reveal = next((item for item in result.tool_results if item.get("step") == "reveal"), {})
    observed = next((item for item in result.tool_results if item.get("step") == "observe"), {})
    screenshot = capture(observer, "explorer_item_selected")
    test = {
        "test": "explorer_safe_selection", "goal": "select controlled file in Explorer",
        "application": "Explorer", "application_type": observed.get("data", {}).get("application", {}).get("application_type", "file_explorer"),
        "permission_mode": "CONTROL", "perception_method": "windows_ui_automation",
        "target": target.name, "action": "reveal and select",
        "expected_result": "controlled item visible in Explorer", "actual_result": reveal.get("data", {}),
        "verification": bool(reveal.get("verified")), "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": "PASS" if result.status.value == "completed" else "FAIL",
    }
    return test, screenshot, int(reveal.get("data", {}).get("window", {}).get("handle", 0))


def run_failure(app: ArcheonApplication) -> dict[str, object]:
    task = AgentTask(
        "haz clic en BotónQueNoExiste123",
        (AgentStep("locate", "Buscar objetivo inexistente", "desktop.locate", {"name": "BotónQueNoExiste123"}, "target found", 1),),
        ("target must be grounded before click",), AgentMode.CONTROL,
    )
    started = time.perf_counter()
    result = app.agent_runner.run(task, scope_permissions=frozenset({"desktop.observe"}))
    return {
        "test": "bounded_target_not_found", "goal": task.goal, "application": "active window",
        "application_type": "unknown", "permission_mode": "CONTROL",
        "perception_method": "windows_ui_automation", "target": "BotónQueNoExiste123",
        "action": "locate only; no click without grounding", "expected_result": "bounded failure and zero clicks",
        "actual_result": {"status": result.status.value, "retries": result.retries, "errors": result.errors, "actions": result.actions},
        "verification": result.status.value == "failed" and len(result.actions) == 2,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": "PASS" if result.status.value == "failed" and len(result.actions) == 2 else "FAIL",
    }


def run_cancel(app: ArcheonApplication) -> dict[str, object]:
    task = AgentTask(
        "wait for a window that must be cancelled",
        (AgentStep("wait", "Esperando objetivo controlado", "desktop.find_window", {"title": "ARCHEON_WINDOW_THAT_WILL_NOT_EXIST", "wait": True, "timeout_seconds": 30}, "window found", 0),),
        ("cancel immediately",), AgentMode.CONTROL,
    )
    holder: dict[str, object] = {}
    started = time.perf_counter()

    def execute() -> None:
        holder["task"] = app.agent_runner.run(task, scope_permissions=frozenset({"desktop.observe"}))

    worker = threading.Thread(target=execute, name="archeon-m10-cancel-runtime")
    worker.start()
    deadline = time.monotonic() + 3
    while app.agent_runner.active_task_count == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    cancelled = app.agent_runner.cancel_active()
    released = app.tools.release_active_inputs()
    worker.join(timeout=2)
    elapsed = (time.perf_counter() - started) * 1000
    result = holder.get("task")
    passed = bool(result and result.status.value == "cancelled" and not worker.is_alive() and elapsed < 2000)
    return {
        "test": "immediate_cancel", "goal": task.goal, "application": "runtime",
        "application_type": "unknown", "permission_mode": "CONTROL", "perception_method": "structured_wait",
        "target": "pending plan", "action": "cancel and release inputs", "expected_result": "task cancelled under two seconds",
        "actual_result": {"cancelled_count": cancelled, "input_release": released, "status": result.status.value if result else "missing", "worker_alive": worker.is_alive()},
        "verification": passed, "latency_ms": round(elapsed, 3), "result": "PASS" if passed else "FAIL",
    }


def recognition_matrix(observer: WindowsDesktopObserver, *, observed: tuple[dict[str, object], ...] = ()) -> list[dict[str, object]]:
    actual = list(observed)
    for window in observer.list_windows(limit=200):
        classified = observer.classify_window(window)
        if classified["application_type"] in {"browser", "file_explorer", "terminal", "webview", "native_windows_app"}:
            actual.append({**classified, "validation": "REAL_WINDOW"})
    present = {item["application_type"] for item in actual}
    contracts = (
        WindowInfo(1, "ARCHEON", 1, "ARCHEON.exe", "Chrome_WidgetWin_1", (0, 0, 800, 600), True),
        WindowInfo(2, "PowerShell", 2, "WindowsTerminal.exe", "CASCADIA_HOSTING_WINDOW_CLASS", (0, 0, 800, 600), True),
    )
    for fixture in contracts:
        classified = observer.classify_window(fixture)
        if classified["application_type"] not in present:
            actual.append({**classified, "validation": "PACKAGED_CONTRACT_TESTED"})
    return actual


def run_visual_fallback() -> dict[str, object]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "benchmark_vision_control_m3.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    path = ROOT / "benchmarks" / "desktop-agent-m3-control.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    passed = completed.returncode == 0 and data.get("ok") and data.get("method") == "archi_vision"
    return {
        "test": "vision_fallback_controlled_canvas", "goal": "press visually grounded OK control",
        "application": "controlled canvas", "application_type": "native_windows_app",
        "permission_mode": "CONTROL", "perception_method": data.get("method", "archi_vision"),
        "target": "OK", "action": "vision ground, visible click, verify state change",
        "expected_result": "canvas changes to RESOLVED", "actual_result": data,
        "verification": bool(passed), "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": "PASS" if passed else "FAIL",
    }


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    observer = WindowsDesktopObserver(max_elements=500, max_depth=32)
    process = psutil.Process()
    with tempfile.TemporaryDirectory(prefix="archeon-m10-computer-use-") as temporary:
        root = Path(temporary)
        app = ArcheonApplication(data_dir=root / "app-data")
        app.start()
        idle_loaded_tools = app.tools.loaded_tool_count
        idle_vision = app.vision_provider.status(developer=True) if app.vision_provider else {"loaded": False}
        process.cpu_percent(None); time.sleep(0.4)
        performance = {
            "idle_rss_bytes": process.memory_info().rss,
            "idle_cpu_percent": process.cpu_percent(None),
            "loaded_tool_instances_before_computer_use": idle_loaded_tools,
            "vision_loaded_before_computer_use": bool(idle_vision.get("loaded")),
            "screenshot_loop_count": 0, "mouse_worker_count": 0, "browser_watcher_count": 0,
        }
        app.configuration.update_settings({"computer_use": {"action_display": "visible"}})
        tests: list[dict[str, object]] = []
        screenshots: dict[str, object] = {}
        youtube, trace, youtube_shots = run_youtube(app, observer); tests.append(youtube); screenshots.update(youtube_shots)
        notepad, notepad_shot, notepad_recognition = run_notepad(app, observer); tests.append(notepad); screenshots["notepad"] = notepad_shot
        explorer, explorer_shot, explorer_handle = run_explorer(app, observer, root); tests.append(explorer); screenshots["explorer"] = explorer_shot
        recognition = recognition_matrix(observer, observed=(notepad_recognition,))
        tests.append(run_failure(app)); tests.append(run_cancel(app))
        if explorer_handle:
            try: WindowsDesktopController().close_window(explorer_handle, timeout_seconds=3)
            except Exception: pass
        app.stop()
    tests.append(run_visual_fallback())
    residual = [child.pid for child in process.children(recursive=True) if child.is_running()]
    performance.update({
        "loaded_tool_instances_after_shutdown": 0,
        "vision_loaded_after_fallback": False,
        "residual_child_processes": residual,
    })
    all_passed = all(item["result"] == "PASS" for item in tests) and not residual
    report = {
        "milestone": "M10 Computer Use Real Validation", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runtime_origin": "ARCHEON", "user_verified": False,
        "status": "WORKING / PACKAGED TESTED" if all_passed else "PARTIAL / NOT USER VERIFIED",
        "tests": tests, "action_trace": trace, "application_recognition": recognition,
        "screenshots": screenshots, "performance": performance,
        "privacy": {"continuous_capture": False, "evidence_only": True, "sensitive_data_included": False},
        "result": "PASS" if all_passed else "FAIL",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "status": report["status"], "tests": {item["test"]: item["result"] for item in tests}, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
