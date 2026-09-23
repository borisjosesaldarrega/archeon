"""Verify real WASAPI Wake → manual listen → Wake ownership handoff."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from queue import Empty

from archeon.app import ArcheonApplication
from archeon.core.paths import AppPaths


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="archeon-handoff-") as temporary:
        app = ArcheonApplication(data_dir=Path(temporary), port=0)
        events = app.events.subscribe("voice.cycle.*", "wake.monitor.*", max_queue=64)
        app.configuration.update_settings({
            "storage": {"model_dir": str(AppPaths.discover().default_model_dir)},
            "assistant": {
                "wake_name": "Archeon",
                "wake_word_enabled": True,
                "activation_mode": "wake_word",
            },
            "voice": {"barge_in": False},
        })
        app.start()
        deadline = time.monotonic() + 3.0
        while not app.voice.status()["wake_monitor_active"] and time.monotonic() < deadline:
            time.sleep(0.05)
        before = app.voice.status()
        manual = app.handle_action("voice.listen")
        terminal_event = None
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                event = events.get(timeout=0.25)
            except Empty:
                continue
            if event.type in {"voice.cycle.completed", "voice.cycle.cancelled", "voice.cycle.error"}:
                terminal_event = event.to_dict()
                break
        deadline = time.monotonic() + 3.0
        while not app.voice.status()["wake_monitor_active"] and time.monotonic() < deadline:
            time.sleep(0.05)
        after = app.voice.status()
        terminal_error = str((terminal_event or {}).get("payload", {}).get("error", ""))
        acceptable_terminal = bool(
            terminal_event
            and (
                terminal_event["type"] == "voice.cycle.completed"
                or terminal_error in {"no_speech_detected", "empty_transcription"}
            )
        )
        result = {
            "ok": bool(
                before["wake_monitor_active"]
                and manual.get("ok")
                and acceptable_terminal
                and after["wake_monitor_active"]
                and after["wake_monitor_state"] != "error"
                and app.audio.backend_loaded
            ),
            "before": before,
            "manual": manual,
            "terminal_event": terminal_event,
            "after": after,
            "wake_reacquired_audio": app.audio.backend_loaded,
        }
        app.configuration.update_settings({"assistant": {"wake_word_enabled": False}})
        app.voice.sync_wake_word()
        app.stop()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
