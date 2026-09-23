"""Run the three M10 music requests against real configured providers."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "M10_MEDIA_MANUAL_REGRESSIONS.json"
STATE_OUTPUT = ROOT / "benchmarks" / "M10_MEDIA_PLAYBACK_STATE_VALIDATION.json"
REQUESTS = (
    ("resolver_limon_y_sal", "reproduce limon y sal de julieta venegas"),
    ("original_se_fue_la_luz", "reproduce se fue la luz de latin mafia"),
    ("metadata_hello_cotto", "reproduce hello cotto de duki"),
)


def main() -> int:
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="archeon-m10-media-") as temporary:
        data_dir = Path(temporary)
        application = ArcheonApplication(
            data_dir=data_dir, port=0,
            auth_provider=DevelopmentAuthProvider(data_dir / "development-auth.json"),
            auth_vault=MemorySessionVault(),
        )
        application.start()
        application.media.set_volume(0.0)
        try:
            for case_id, command in REQUESTS:
                started = time.perf_counter()
                result = application.handle_command(command)
                data = result.get("data", {})
                confirmation_required = bool(data.get("confirmation_required"))
                playback_samples: list[dict[str, object]] = []
                deadline = time.monotonic() + 4.0
                status = application.media.status()
                while status["state"] in {"buffering", "playing"} and time.monotonic() < deadline:
                    playback_samples.append({
                        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
                        "state": status["state"], "position_ms": status["position_ms"],
                        "evidence": status.get("playback_evidence", {}),
                    })
                    if status.get("playback_evidence", {}).get("verified_playing") and len(playback_samples) >= 2:
                        break
                    time.sleep(0.12)
                    status = application.media.status()
                control_validation: dict[str, object] | None = None
                if status.get("playback_evidence", {}).get("verified_playing"):
                    before_pause = status["position_ms"]
                    paused = application.media.pause()
                    time.sleep(0.25)
                    paused_after_wait = application.media.status()
                    resumed = application.media.resume()
                    resume_deadline = time.monotonic() + 3.0
                    resumed_after_wait = application.media.status()
                    while (
                        not resumed_after_wait.get("playback_evidence", {}).get("verified_playing")
                        and time.monotonic() < resume_deadline
                    ):
                        time.sleep(0.10)
                        resumed_after_wait = application.media.status()
                    control_validation = {
                        "before_pause_ms": before_pause,
                        "paused_state": paused["state"],
                        "paused_position_ms": paused_after_wait["position_ms"],
                        "pause_clock_stable": abs(paused_after_wait["position_ms"] - before_pause) <= 80,
                        "resume_initial_state": resumed["state"],
                        "resume_verified_state": resumed_after_wait["state"],
                        "resume_position_ms": resumed_after_wait["position_ms"],
                        "resume_continued_without_restart": resumed_after_wait["position_ms"] >= before_pause,
                        "verified_playing": resumed_after_wait.get("playback_evidence", {}).get("verified_playing", False),
                    }
                    status = resumed_after_wait
                verified_audio = bool(status.get("playback_evidence", {}).get("verified_playing"))
                outcome = (
                    "verified_audio" if verified_audio else
                    "awaiting_alternative_confirmation" if confirmation_required else
                    "not_found" if not result.get("ok") else "resolved_without_verified_audio"
                )
                if status["state"] in {"buffering", "playing", "paused"}:
                    application.media.stop_playback()
                cases.append({
                    "test": case_id,
                    "command": command,
                    "command_ok": bool(result.get("ok")),
                    "outcome": outcome,
                    "case_passed": verified_audio,
                    "message": result.get("message"),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "resolve_trace": result.get("data", {}).get("resolve_trace", {}),
                    "media_state_after_request": status,
                    "playback_samples": playback_samples,
                    "control_validation": control_validation,
                    "state_after_cleanup": application.media.status()["state"],
                })
        finally:
            application.stop()
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scenario": "m10_real_provider_resolution_no_mocks",
        "music_end_to_end_status": "PARTIAL",
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    false_playing = [
        item["test"] for item in cases
        if item["outcome"] != "verified_audio"
        and item["media_state_after_request"]["state"] == "playing"
    ]
    verified_cases = [
        item for item in cases
        if item["media_state_after_request"].get("playback_evidence", {}).get("verified_playing")
    ]
    state_payload = {
        "timestamp": payload["timestamp"],
        "scenario": "m10_lifecycle_state_is_not_playback_state",
        "result": "PASS" if not false_playing and verified_cases else "FAIL",
        "rules": {
            "component_running_does_not_imply_audio_playing": not false_playing,
            "playing_requires_active_track": all(
                item["media_state_after_request"]["playback_evidence"]["active_track"]
                for item in verified_cases
            ),
            "playing_requires_playable_source": all(
                item["media_state_after_request"]["playback_evidence"]["playable_source"]
                for item in verified_cases
            ),
            "playing_requires_active_backend": all(
                item["media_state_after_request"]["playback_evidence"]["active_backend"]
                for item in verified_cases
            ),
            "playing_requires_advancing_clock": all(
                item["media_state_after_request"]["playback_evidence"]["clock_advanced"]
                for item in verified_cases
            ),
            "pause_keeps_clock_stable": all(
                item["control_validation"]["pause_clock_stable"]
                for item in verified_cases if item["control_validation"]
            ),
            "resume_continues_without_restart": all(
                item["control_validation"]["resume_continued_without_restart"]
                for item in verified_cases if item["control_validation"]
            ),
            "cleanup_returns_stopped": all(item["state_after_cleanup"] == "stopped" for item in cases),
        },
        "false_playing_cases": false_playing,
        "verified_playing_cases": [item["test"] for item in verified_cases],
        "cases": [
            {
                "test": item["test"],
                "outcome": item["outcome"],
                "state": item["media_state_after_request"]["state"],
                "evidence": item["media_state_after_request"].get("playback_evidence", {}),
                "control_validation": item["control_validation"],
                "state_after_cleanup": item["state_after_cleanup"],
            }
            for item in cases
        ],
    }
    STATE_OUTPUT.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "music_end_to_end_status": payload["music_end_to_end_status"],
        "cases": [{"test": item["test"], "outcome": item["outcome"],
                   "case_passed": item["case_passed"], "elapsed_ms": item["elapsed_ms"]}
                  for item in cases],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
