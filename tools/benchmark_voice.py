"""Repeatable real-provider voice benchmarks for the current Windows host."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from threading import Event, Timer

import psutil


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks"


def synthesize_input(path: Path) -> tuple[bytes, int]:
    """Create deterministic Spanish speech through Windows SAPI at 16 kHz."""
    import comtypes
    import comtypes.client

    comtypes.CoInitialize()
    try:
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        audio_format = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        audio_format.Type = 18  # SAFT16kHz16BitMono
        stream.Format = audio_format
        stream.Open(str(path), 3, False)  # SSFMCreateForWrite
        voice.AudioOutputStream = stream
        voice.Speak("estado del sistema", 0)
        stream.Close()
    finally:
        comtypes.CoUninitialize()
    with wave.open(str(path), "rb") as source:
        return source.readframes(source.getnframes()), source.getframerate()


def worker(scenario: str) -> int:
    from archeon.audio import AudioManager, AudioMode, AudioSessionConfig
    from archeon.audio.wasapi import WasapiSharedCapture
    from archeon.core.events import EventBus
    from archeon.core.paths import AppPaths
    from archeon.voice import VoicePipeline
    from archeon.voice.providers import SapiTextToSpeech, VoskSpeechToText

    events = EventBus()
    audio = AudioManager(events)
    audio.start()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    model_root = AppPaths.discover().default_model_dir
    try:
        if scenario == "listening":
            audio.register_backend("wasapi_shared", WasapiSharedCapture)
            stop = Event()
            backend = audio.acquire(
                AudioMode.CAPTURING,
                config=AudioSessionConfig(sample_rate=16_000, channels=1, block_ms=20),
            )
            print(json.dumps({"event": "ready", "pid": os.getpid()}), flush=True)
            Timer(3.0, stop.set).start()
            backend.capture(stop, lambda _chunk: True)
            audio.release()
            result = {"frames_discarded": True, "audio_released": not audio.backend_loaded}
        elif scenario == "tts":
            tts = SapiTextToSpeech()
            print(json.dumps({"event": "ready", "pid": os.getpid()}), flush=True)
            tts.speak("Prueba de rendimiento de voz de Archeon.", Event(), volume=20, rate=1)
            result = {"provider": tts.name}
        else:
            temporary = tempfile.TemporaryDirectory()
            pcm, sample_rate = synthesize_input(Path(temporary.name) / "input.wav")
            if scenario == "stt":
                stt = VoskSpeechToText(model_root / "vosk-model-small-es-0.42")
                print(json.dumps({"event": "ready", "pid": os.getpid()}), flush=True)
                text = stt.transcribe(pcm, sample_rate)
                stt.unload()
                result = {"provider": stt.name, "text": text, "model_released": not stt.loaded}
            elif scenario == "full_cycle":
                pipeline = VoicePipeline(
                    events,
                    audio,
                    lambda text: {"ok": True, "message": f"Orden recibida: {text}"},
                    model_root,
                    barge_in_provider=lambda: False,
                    tts_config_provider=lambda: {"volume": 20, "rate": 1},
                )
                pipeline._capture_utterance = lambda: pcm
                pipeline.start()
                print(json.dumps({"event": "ready", "pid": os.getpid()}), flush=True)
                started = pipeline.start_cycle()
                thread = pipeline._thread
                if thread is not None:
                    thread.join(timeout=20.0)
                result = {
                    "started": started,
                    "completed": bool(thread is not None and not thread.is_alive()),
                    "audio_released": not audio.backend_loaded,
                }
                pipeline.stop()
            else:
                raise ValueError(f"unknown scenario: {scenario}")
        print(json.dumps({"event": "complete", "result": result}, ensure_ascii=False), flush=True)
        return 0
    finally:
        audio.stop()
        events.close()
        if temporary is not None:
            temporary.cleanup()


def process_family(root: psutil.Process) -> list[psutil.Process]:
    try:
        candidates = [root, *root.children(recursive=True)]
        return [process for process in candidates if process.is_running()]
    except psutil.NoSuchProcess:
        return []


def measure(scenario: str) -> dict[str, object]:
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker", scenario],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    ready_line = process.stdout.readline()
    if not ready_line:
        _, stderr = process.communicate(timeout=3)
        raise RuntimeError(f"{scenario} worker failed before ready: {stderr.strip()}")
    ready = json.loads(ready_line)
    if ready.get("event") != "ready":
        raise RuntimeError(f"worker did not become ready: {ready}")
    root = psutil.Process(int(ready["pid"]))
    known: dict[int, psutil.Process] = {}
    for item in process_family(root):
        known[item.pid] = item
        item.cpu_percent(None)
    started = time.perf_counter()
    rss_samples: list[int] = []
    private_samples: list[int] = []
    cpu_samples: list[float] = []
    handle_peak = 0
    thread_peak = 0
    while root.is_running():
        time.sleep(0.05)
        rss = private = 0
        cpu = 0.0
        for item in process_family(root):
            known.setdefault(item.pid, item)
        for item in tuple(known.values()):
            try:
                memory = item.memory_info()
                rss += memory.rss
                private += getattr(memory, "private", memory.rss)
                cpu += item.cpu_percent(None)
                thread_peak = max(thread_peak, item.num_threads())
                if hasattr(item, "num_handles"):
                    handle_peak = max(handle_peak, item.num_handles())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rss_samples.append(rss)
        private_samples.append(private)
        cpu_samples.append(cpu)
    stdout_tail, stderr = process.communicate(timeout=3)
    completion = json.loads(stdout_tail.strip().splitlines()[-1]) if stdout_tail.strip() else {}
    return {
        "scenario": scenario,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "ram_mb_avg": round(mean(rss_samples) / 1_048_576, 3),
        "ram_mb_peak": round(max(rss_samples) / 1_048_576, 3),
        "private_mb_avg": round(mean(private_samples) / 1_048_576, 3),
        "private_mb_peak": round(max(private_samples) / 1_048_576, 3),
        "cpu_percent_avg": round(mean(cpu_samples), 3),
        "cpu_percent_peak": round(max(cpu_samples), 3),
        "process_count": len(known),
        "handles_peak_per_process": handle_peak,
        "threads_peak_per_process": thread_peak,
        "result": completion.get("result"),
        "exit_code": process.returncode,
        "stderr": stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("listening", "stt", "tts", "full_cycle"))
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "scenarios": [measure(name) for name in ("listening", "stt", "tts", "full_cycle")],
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "voice-latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    with (RESULTS / "voice-history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
