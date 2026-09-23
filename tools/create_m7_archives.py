"""Create, reopen, inspect and hash-compare controlled M7 archives."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from archeon.artifacts import ArchiveEngineProvider


OUTPUT = Path(r"C:\Users\salda\Downloads\ARCHI-Artifactos-M7")
PROJECT = OUTPUT / "ARCHI_TaskBoard"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""): value.update(chunk)
    return value.hexdigest()


def project_hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)).replace("\\", "/"): digest(path) for path in sorted(root.rglob("*")) if path.is_file()}


def main() -> int:
    provider = ArchiveEngineProvider(); expected = project_hashes(PROJECT); reports: dict[str, object] = {}
    for suffix in ("zip", "tar", "tar.gz"):
        target = OUTPUT / f"ARCHI_TaskBoard.{suffix}"
        target.unlink(missing_ok=True)
        created_started = time.perf_counter(); created = provider.create(target, [PROJECT]); create_ms = (time.perf_counter() - created_started) * 1000
        index_started = time.perf_counter(); index = provider.list(target); inspect_ms = (time.perf_counter() - index_started) * 1000
        member = provider.read_member(target, "ARCHI_TaskBoard/app.js")
        with tempfile.TemporaryDirectory(prefix=f"archi-m7-{suffix.replace('.', '-')}-") as temporary:
            extracted_root = Path(temporary) / "extracted"
            extract_started = time.perf_counter(); extracted = provider.extract(target, extracted_root); extract_ms = (time.perf_counter() - extract_started) * 1000
            actual = project_hashes(extracted_root / "ARCHI_TaskBoard")
        reports[suffix] = {
            "path": str(target), "created": created["valid"], "reopened": index["member_count"] >= 4,
            "integrity": provider.verify(target)["valid"], "safe_to_extract": index["safe_to_extract"],
            "member_count": index["member_count"], "tree": index["tree"], "selective_read": member["textual"] and "localStorage" in str(member["text"]),
            "extracted": extracted["verified"], "hashes_match": actual == expected,
            "risk_counts": index["risk_counts"], "sha256": created["sha256"],
            "performance_ms": {"create": round(create_ms, 3), "inspect": round(inspect_ms, 3), "extract": round(extract_ms, 3)},
        }
    capabilities = provider.capabilities()
    report = {"archives": reports, "capabilities": capabilities, "all_native_passed": all(all(value[key] for key in ("created", "reopened", "integrity", "safe_to_extract", "selective_read", "extracted", "hashes_match")) for value in reports.values())}
    target = OUTPUT / "M7_ARCHIVE_VALIDATION.json"; target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_native_passed": report["all_native_passed"], "formats": list(reports), "capabilities": capabilities}, ensure_ascii=True))
    return 0 if report["all_native_passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
