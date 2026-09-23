"""Run the first local-AI milestone through the real ARCHEON composition root."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psutil

from archeon.app import ArcheonApplication
from archeon.intelligence import GenerationRequest, LlamaCppProvider
from archeon.intelligence.models import ModelRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", action="append")
    parser.add_argument("--models-dir", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--model-id", default="qwen3-4b-q4-k-m")
    args = parser.parse_args()
    if args.models_dir or args.runtime_dir:
        if not args.models_dir or not args.runtime_dir:
            parser.error("--models-dir and --runtime-dir must be provided together")
        return run_direct(args)
    available_before = psutil.virtual_memory().available
    application = ArcheonApplication(port=0)
    application.start()
    state_at_start = application.local_ai.model_state.value
    prompts = args.prompt or [
        "¿Qué eres? Responde brevemente en español.",
        "Explícame qué es una API en un párrafo claro.",
    ]
    results = []
    for prompt in prompts:
        started = time.perf_counter()
        result = application.handle_command(prompt)
        results.append({
            "ok": bool(result.get("ok")), "prompt": prompt,
            "response": result.get("message"), "data": result.get("data", {}),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        })
    status_loaded = application.local_ai.status()
    process_metrics = {}
    if status_loaded.get("pid"):
        process = psutil.Process(int(status_loaded["pid"]))
        memory = process.memory_full_info()
        process_metrics = {"rss_bytes": memory.rss, "private_bytes": memory.private}
    available_loaded = psutil.virtual_memory().available
    application.local_ai.unload()
    time.sleep(3)
    state_after_unload = application.local_ai.model_state.value
    available_after_unload = psutil.virtual_memory().available
    lingering = [
        item.pid for item in psutil.process_iter(["name"])
        if "llama-server" in (item.info["name"] or "").lower()
    ]
    application.stop()
    report = {
        "ok": all(item["ok"] for item in results), "results": results,
        "state_at_start": state_at_start,
        "state_loaded": status_loaded.get("state"), "state_after_unload": state_after_unload,
        "process": process_metrics, "available_memory_before": available_before,
        "available_memory_loaded": available_loaded,
        "available_memory_after_unload": available_after_unload,
        "llama_processes_after_unload": lingering,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] and state_at_start == "unloaded" and not lingering else 1


def run_direct(args: argparse.Namespace) -> int:
    """Profile an installed model without touching the user's ARCHEON configuration."""
    registry = ModelRegistry(args.models_dir)
    descriptor = registry.get(args.model_id)
    if descriptor is None:
        raise ValueError("registered_model_missing")
    executable = args.runtime_dir / "llama-server.exe"
    provider = LlamaCppProvider(
        executable, registry.model_path(descriptor), descriptor,
        context_size=4096, threads=6, idle_timeout_seconds=0, backend="cpu",
    )
    prompts = args.prompt or [
        "¿Qué eres? Responde brevemente en español.",
        "Explica en una frase qué es una API.",
    ]
    results = []
    state_at_start = provider.state.value
    for prompt in prompts:
        generated = provider.generate(GenerationRequest(
            messages=(
                {"role": "system", "content": "Eres ARCHEON. Responde brevemente en español."},
                {"role": "user", "content": prompt},
            ),
            max_tokens=96,
            temperature=0.2,
            enable_thinking=False,
        ))
        results.append({
            "prompt": prompt,
            "response": generated.text,
            "prompt_tokens": generated.prompt_tokens,
            "completion_tokens": generated.completion_tokens,
            "load_ms": round(generated.load_ms, 3),
            "first_token_ms": round(generated.first_token_ms, 3) if generated.first_token_ms is not None else None,
            "total_ms": round(generated.total_ms, 3),
            "tokens_per_second": round(
                generated.completion_tokens / max(0.001, (generated.total_ms - generated.load_ms) / 1000), 3
            ),
            "stages": dict(generated.timings),
        })
    status = provider.status()
    process_metrics = {}
    if status.get("pid"):
        memory = psutil.Process(int(status["pid"])).memory_full_info()
        process_metrics = {"rss_bytes": memory.rss, "private_bytes": memory.private}
    provider.unload()
    lingering = [
        item.pid for item in psutil.process_iter(["name"])
        if "llama-server" in (item.info["name"] or "").lower()
    ]
    report = {
        "ok": bool(results) and all(item["response"] for item in results),
        "mode": "direct_read_only_config",
        "state_at_start": state_at_start,
        "results": results,
        "process": process_metrics,
        "state_after_unload": provider.state.value,
        "llama_processes_after_unload": lingering,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] and state_at_start == "unloaded" and not lingering else 1


if __name__ == "__main__":
    raise SystemExit(main())
