"""Create and statically validate the M8 TaskBoard package."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archeon.artifacts import ArchiveEngineProvider  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    out = Path.home() / "Downloads" / "ARCHI-Artifactos-M8"
    source = out / "ARCHI_TaskBoard_M8"; target = out / "ARCHI_TaskBoard_M8.zip"
    if target.exists(): target.unlink()
    provider = ArchiveEngineProvider(); created = provider.create(target, [source]); listing = provider.list(target); verified = provider.verify(target)
    analysis = provider.analyze_project(target)
    with tempfile.TemporaryDirectory(prefix="archi-m8-taskboard-") as temp:
        destination = Path(temp) / "extracted"
        extracted = provider.extract(target, destination)
        restored = destination / "ARCHI_TaskBoard_M8"
        hashes_match = all(digest(path) == digest(restored / path.name) for path in source.iterdir() if path.is_file())
    report = {"created": created["valid"], "verified": verified["valid"], "safe_to_extract": listing["safe_to_extract"], "member_count": listing["member_count"], "tree": listing["tree"], "project_analysis": analysis, "extracted": extracted["verified"], "hashes_match": hashes_match, "sha256": verified["sha256"]}
    (out / "M8_ARCHIVE_VALIDATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True)); return 0 if all((report["created"], report["verified"], report["safe_to_extract"], report["extracted"], report["hashes_match"])) else 1


if __name__ == "__main__": raise SystemExit(main())
