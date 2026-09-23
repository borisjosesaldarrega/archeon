"""Packaged M8 quality-engine latency, resources, lazy load and residue."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist-artifacts-m8" / "Archeo32n" / "Archeo32n.exe"
sys.path.insert(0, str(ROOT / "src"))


def sample(process: psutil.Process) -> dict[str, float | int]:
    process.cpu_percent(None); time.sleep(0.35); tree = [process, *process.children(recursive=True)]; living = [item for item in tree if item.is_running()]
    return {"rss_mib": round(sum(item.memory_info().rss for item in living)/1024/1024,3), "cpu_percent": round(sum(item.cpu_percent(None) for item in living),3), "processes":len(living), "threads":sum(item.num_threads() for item in living)}


def run_case(data: Path, *, artifacts: bool) -> dict[str, object]:
    args=[str(EXE),"--headless","--auto-exit","3","--allow-multiple","--data-dir",str(data)];
    if artifacts: args.append("--benchmark-desktop-m4")
    started=time.perf_counter(); process=subprocess.Popen(args,creationflags=0x08000000); tracked=psutil.Process(process.pid); smoke=data/"desktop-agent-m4-smoke.json"; deadline=time.monotonic()+2.2
    while artifacts and time.monotonic()<deadline and not smoke.exists(): time.sleep(.05)
    time.sleep(.55 if artifacts else 1.2); resources=sample(tracked); children=[item.pid for item in tracked.children(recursive=True)]; exit_code=process.wait(timeout=20); time.sleep(.2)
    return {"resources":resources,"exit_code":exit_code,"residual_children":[pid for pid in children if psutil.pid_exists(pid)],"wall_ms":round((time.perf_counter()-started)*1000,3),"smoke":json.loads(smoke.read_text()) if smoke.exists() else None}


def quality_latency() -> dict[str, float | int]:
    from archeon.artifacts import ArtifactQualityEngine
    engine=ArtifactQualityEngine(); evidence={"technical_validity":True,"instruction_compliance":True,"visual_design":.84,"media_relevance":.72,"thematic_visuals":5,"minimum_thematic_visuals":5}
    values=[]
    for _ in range(5000):
        started=time.perf_counter_ns(); engine.review("benchmark",evidence); values.append((time.perf_counter_ns()-started)/1_000_000)
    values.sort(); return {"iterations":len(values),"median_ms":round(statistics.median(values),4),"p95_ms":round(values[int(len(values)*.95)-1],4),"max_ms":round(max(values),4)}


def main() -> int:
    if not EXE.exists(): raise FileNotFoundError(EXE)
    with tempfile.TemporaryDirectory(prefix="archeon-m8-idle-") as idle_dir,tempfile.TemporaryDirectory(prefix="archeon-m8-active-") as active_dir:
        idle=run_case(Path(idle_dir),artifacts=False); active=run_case(Path(active_dir),artifacts=True)
    files=[item for item in EXE.parent.rglob("*") if item.is_file()]
    report={"milestone":"Artifact Quality M8","packaged":True,"build":{"path":str(EXE),"bytes":sum(item.stat().st_size for item in files),"files":len(files),"gguf":sum(item.suffix.casefold()==".gguf" for item in files),"ffmpeg":sum("ffmpeg" in item.name.casefold() or "avcodec" in item.name.casefold() for item in files)},"idle":idle,"artifact_loaded":active,"quality_review":quality_latency(),"generation":{"xlsx":json.loads((ROOT/"tmp/m8-artifacts/xlsx-performance.json").read_text()),"presentations":json.loads((ROOT/"tmp/m8-artifacts/presentation-performance.json").read_text())}}
    target=ROOT/"benchmarks/artifacts-m8-packaged.json";target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report,ensure_ascii=True))
    valid=idle["exit_code"]==active["exit_code"]==0 and active["smoke"] and active["smoke"]["ok"]
    return 0 if valid and not idle["residual_children"] and not active["residual_children"] else 1


if __name__=="__main__": raise SystemExit(main())
