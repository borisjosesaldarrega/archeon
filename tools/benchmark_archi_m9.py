"""Measure three cold and five warm ARCHI requests through the real app."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from archeon.app import ArcheonApplication


def metrics(result: dict[str, object], elapsed_ms: float) -> dict[str, object]:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    measured = data.get("metrics", {}) if isinstance(data, dict) else {}
    return {
        "ok": bool(result.get("ok")), "elapsed_ms": round(elapsed_ms, 3),
        "load_ms": measured.get("load_ms"), "first_token_ms": measured.get("first_token_ms"),
        "generation_tokens_per_second": measured.get("tokens_per_second"),
        "legacy_end_to_end_tokens_per_second": measured.get("legacy_end_to_end_tokens_per_second"),
        "prompt_tokens": (data.get("usage", {}) or {}).get("prompt_tokens") if isinstance(data, dict) else None,
        "completion_tokens": (data.get("usage", {}) or {}).get("completion_tokens") if isinstance(data, dict) else None,
        "context": measured.get("context"), "response_budget": measured.get("response_budget"),
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    summary: dict[str, object] = {"runs": len(rows), "passed": sum(bool(row.get("ok")) for row in rows)}
    for key in ("elapsed_ms", "load_ms", "first_token_ms", "generation_tokens_per_second"):
        sample = values(key)
        if sample:
            summary[key] = {"median": round(statistics.median(sample), 3), "min": round(min(sample), 3), "max": round(max(sample), 3)}
    return summary


def main() -> int:
    app = ArcheonApplication(port=0); app.start()
    process = psutil.Process()
    baseline_rss = process.memory_info().rss
    cold: list[dict[str, object]] = []
    for index in range(3):
        app.local_ai.unload(); time.sleep(.5)
        started = time.perf_counter()
        result = app.handle_command(f"Prueba fría {index + 1}: responde solo OK.")
        cold.append(metrics(result, (time.perf_counter() - started) * 1000))
    warm: list[dict[str, object]] = []
    for prompt in (
        "Responde solo: uno.", "Responde solo: dos.", "Responde solo: tres.",
        "Define latencia en exactamente una oración.",
        "Explica DNS en exactamente una oración, sin listas.",
    ):
        started = time.perf_counter(); result = app.handle_command(prompt)
        warm.append(metrics(result, (time.perf_counter() - started) * 1000))
    loaded_status = app.local_ai.status(); loaded_rss = process.memory_info().rss
    app.local_ai.unload(); time.sleep(2)
    after_rss = process.memory_info().rss
    lingering = [item.pid for item in psutil.process_iter(["name"]) if "llama-server" in (item.info["name"] or "").lower()]
    app.stop()
    report = {
        "ok": all(row["ok"] for row in cold + warm) and not lingering,
        "cold": cold, "warm": warm, "cold_summary": summarize(cold), "warm_summary": summarize(warm),
        "process_rss_bytes": {"baseline": baseline_rss, "loaded": loaded_rss, "post_unload": after_rss},
        "provider_loaded_status": loaded_status, "llama_processes_after_unload": lingering,
        "notes": [
            "generation_tokens_per_second excludes prompt evaluation when llama.cpp exposes predicted_per_second",
            "legacy_end_to_end_tokens_per_second is retained only for comparison with earlier reports",
            "results are machine measurements, not USER VERIFIED",
            "a prior first integrity verification measured 26762.616 ms load and 30073.083 ms to first token; the SHA receipt makes subsequent starts faster",
        ],
    }
    output = ROOT / "benchmarks" / "M9_ARCHI_PERFORMANCE.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output), "cold": report["cold_summary"], "warm": report["warm_summary"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
