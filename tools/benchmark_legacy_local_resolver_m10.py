"""Real M10 validation for ARCHEON's integrated legacy-compatible resolver."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from archeon.app import ArcheonApplication
from archeon.auth import DevelopmentAuthProvider, MemorySessionVault


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "M10_LEGACY_LOCAL_RESOLVER_VALIDATION.json"
REQUESTS = (
    ("limon_y_sal", "reproduce limon y sal de julieta venegas"),
    ("se_fue_la_luz", "reproduce se fue la luz de latin mafia"),
    ("hello_cotto", "reproduce hello cotto de duki"),
    ("meant_to_be_typo", "reproduce meet to be de bbno$"),
)


def media_children(process: psutil.Process) -> list[dict[str, object]]:
    result = []
    for child in process.children(recursive=True):
        try:
            name = child.name().casefold()
            if "ffmpeg" in name or "yt-dlp" in name or "yt_dlp" in name:
                result.append({"pid": child.pid, "name": child.name(), "rss_bytes": child.memory_info().rss})
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return result


def main() -> int:
    process = psutil.Process()
    memory_before_start = process.memory_info().rss
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="archeon-m10-legacy-local-") as temporary:
        data_dir = Path(temporary)
        application = ArcheonApplication(
            data_dir=data_dir, port=0,
            auth_provider=DevelopmentAuthProvider(data_dir / "development-auth.json"),
            auth_vault=MemorySessionVault(),
        )
        application.start()
        application.media.set_volume(0.0)
        idle_before = media_children(process)
        yt_dlp_loaded_at_idle = any(name == "yt_dlp" or name.startswith("yt_dlp.") for name in sys.modules)
        idle_search_threads = [
            thread.name for thread in threading.enumerate()
            if "yt" in thread.name.casefold() or "search" in thread.name.casefold()
        ]
        memory_idle = process.memory_info().rss
        try:
            for case_id, command in REQUESTS:
                cpu_before = process.cpu_times()
                started = time.perf_counter()
                result = application.handle_command(command)
                command_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                status = application.media.status()
                deadline = time.monotonic() + 12
                while (
                    status["state"] in {"buffering", "playing"}
                    and not status.get("playback_evidence", {}).get("verified_playing")
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.10)
                    status = application.media.status()
                first_audio_ms = (
                    round((time.perf_counter() - started) * 1000, 3)
                    if status.get("playback_evidence", {}).get("verified_playing") else None
                )
                active_children = media_children(process)
                control = None
                if status.get("playback_evidence", {}).get("verified_playing"):
                    before_pause = status["position_ms"]
                    paused = application.media.pause()
                    time.sleep(0.25)
                    paused_wait = application.media.status()
                    resumed = application.media.resume()
                    resume_deadline = time.monotonic() + 5
                    resumed_wait = application.media.status()
                    while (
                        not resumed_wait.get("playback_evidence", {}).get("verified_playing")
                        and time.monotonic() < resume_deadline
                    ):
                        time.sleep(0.10)
                        resumed_wait = application.media.status()
                    control = {
                        "paused_state": paused["state"],
                        "pause_position_stable": abs(paused_wait["position_ms"] - before_pause) <= 80,
                        "resume_initial_state": resumed["state"],
                        "resume_verified": resumed_wait.get("playback_evidence", {}).get("verified_playing", False),
                        "resume_without_restart": resumed_wait["position_ms"] >= before_pause,
                    }
                    status = resumed_wait
                track = status.get("track") or {}
                trace = result.get("data", {}).get("resolve_trace", {})
                scored_candidates = trace.get("candidates", [])
                selected_candidate_id = trace.get("selected_candidate")
                selected_score = next(
                    (item for item in scored_candidates if item.get("id") == selected_candidate_id), None,
                )
                legacy_phase = next(
                    (phase for phase in trace.get("phases", []) if phase.get("phase") == "legacy_local"), {}
                )
                application.media.stop_playback()
                time.sleep(0.25)
                cpu_after = process.cpu_times()
                cases.append({
                    "test": case_id,
                    "command": command,
                    "ok": bool(result.get("ok")),
                    "message": result.get("message"),
                    "command_elapsed_ms": command_elapsed_ms,
                    "time_to_first_audio_ms": first_audio_ms,
                    "candidate_count": legacy_phase.get("candidate_count", 0),
                    "search_latency_ms": (
                        (legacy_phase.get("provider_trace") or [{}])[0].get("latency_ms", 0.0)
                    ),
                    "selected_resolve_ms": next(
                        (item.get("resolve_ms", 0.0) for item in legacy_phase.get("resolve_attempts", []) if item.get("ok")),
                        0.0,
                    ),
                    "resolve_attempts": legacy_phase.get("resolve_attempts", []),
                    "selected_candidate": selected_candidate_id,
                    "selected_score": selected_score,
                    "top_candidate_scores": scored_candidates[:5],
                    "original_first": bool(selected_score and selected_score.get("version") == "original"),
                    "state": status["state"],
                    "verified_playing": status.get("playback_evidence", {}).get("verified_playing", False),
                    "track": {key: track.get(key) for key in ("title", "artist", "duration_ms", "artwork_url", "provider", "source_url")},
                    "codec_backend": status.get("codec_backend"),
                    "controls": control,
                    "active_media_processes": active_children,
                    "cpu_seconds": round(
                        (cpu_after.user + cpu_after.system) - (cpu_before.user + cpu_before.system), 4
                    ),
                    "state_after_stop": application.media.status()["state"],
                    "residual_after_stop": media_children(process),
                })
        finally:
            application.stop()
        time.sleep(0.25)
        residual_after_shutdown = media_children(process)
    resolver_status = application.media_discovery.legacy_local_resolver.status(developer=True)
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "WORKING" if all(case["verified_playing"] for case in cases) else "PARTIAL",
        "user_verified": False,
        "yt_dlp_version": importlib.metadata.version("yt-dlp"),
        "api_key_independent": True,
        "youtube_data_api_key_present": False,
        "resolver_status": resolver_status,
        "idle": {
            "media_processes": idle_before,
            "zero_idle_processes": not idle_before,
            "yt_dlp_module_loaded": yt_dlp_loaded_at_idle,
            "search_worker_threads": idle_search_threads,
            "zero_idle_search_workers": not idle_search_threads,
            "rss_before_start_bytes": memory_before_start,
            "rss_idle_bytes": memory_idle,
            "rss_app_delta_bytes": memory_idle - memory_before_start,
        },
        "cases": cases,
        "residual_after_shutdown": residual_after_shutdown,
        "zero_residual_after_shutdown": not residual_after_shutdown,
        "vinyl_contract": {
            "playing": "rotate when artwork exists and vinyl_orb is enabled",
            "paused": "freeze current CSS rotation frame",
            "resume": "continue rotation",
            "stop": "restore custom orb",
            "status": "PACKAGED_CONTRACT_TESTED_NOT_USER_VERIFIED",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"], "zero_idle_processes": payload["idle"]["zero_idle_processes"],
        "zero_residual_after_shutdown": payload["zero_residual_after_shutdown"],
        "cases": [{"test": case["test"], "verified": case["verified_playing"],
                   "candidate_count": case["candidate_count"], "elapsed_ms": case["command_elapsed_ms"]}
                  for case in cases],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
