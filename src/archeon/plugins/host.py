"""Minimal child-process host; never imported by the main ARCHEON process."""

from __future__ import annotations
import argparse
import importlib
import json
import os
import sys
from pathlib import Path


def main(
    manifest: str | Path | None = None, *, ready_file: str | Path | None = None,
    ready_token: str = "",
) -> int:
    if manifest is None:
        parser = argparse.ArgumentParser(prog="archeon-plugin-host")
        parser.add_argument("manifest", type=Path)
        parser.add_argument("--ready-file", type=Path, default=None)
        parser.add_argument("--ready-token", default="")
        arguments = parser.parse_args()
        manifest = arguments.manifest; ready_file = arguments.ready_file; ready_token = arguments.ready_token
    manifest_path = Path(manifest).resolve(); data = json.loads(manifest_path.read_text(encoding="utf-8"))
    module_name, attribute = str(data["entrypoint"]).split(":", 1)
    relative = Path(*module_name.split("."))
    module_file = manifest_path.parent / relative.with_suffix(".py")
    package_file = manifest_path.parent / relative / "__init__.py"
    if not module_file.is_file() and not package_file.is_file():
        raise ValueError("plugin_entrypoint_outside_package")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(manifest_path.parent))
    plugin = getattr(importlib.import_module(module_name), attribute)(); plugin.start()
    if ready_file is not None:
        ready_path = Path(ready_file).resolve()
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = ready_path.with_suffix(".tmp")
        temporary.write_text(ready_token or str(os.getpid()), encoding="ascii")
        os.replace(temporary, ready_path)
    try:
        for line in sys.stdin:
            if line.strip() == "stop": break
    finally: plugin.stop()
    return 0


if __name__ == "__main__": raise SystemExit(main())
