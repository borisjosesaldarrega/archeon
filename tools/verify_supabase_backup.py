"""Verify an ARCHEON Supabase logical backup without printing its data."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_TABLES = (
    "users", "sessions", "verification_codes", "memoria", "skills", "comandos",
    "gustos", "chats_mensajes", "archivos", "conversaciones", "mensajes",
    "account_settings", "device_settings",
)
EXPECTED_VIEWS = ("v_conversaciones_decifradas", "v_mensajes_claros", "v_mensajes_decifrados")
EXPECTED_FUNCTIONS = ("archeon_encrypt", "archeon_decrypt", "auto_encrypt_mensajes")
EXPECTED_TRIGGERS = ("encrypt_titulos_trigger", "encrypt_mensajes_trigger", "on_auth_user_created")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(text: str, names: tuple[str, ...], category: str) -> list[str]:
    missing = [name for name in names if name not in text]
    if missing:
        raise ValueError(f"missing {category}: {', '.join(missing)}")
    return list(names)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_supabase_backup.py BACKUP_DIRECTORY")
    directory = Path(sys.argv[1]).resolve()
    files = {name: directory / name for name in ("roles.sql", "schema.sql", "data.sql")}
    for name, path in files.items():
        if not path.is_file() or path.stat().st_size < 64:
            raise ValueError(f"missing or unexpectedly small backup file: {name}")

    schema = files["schema.sql"].read_text(encoding="utf-8", errors="replace")
    roles = files["roles.sql"].read_text(encoding="utf-8", errors="replace")
    data = files["data.sql"].read_text(encoding="utf-8", errors="replace")
    roles_are_sanitized = "RESET ALL;" in roles and "PASSWORD " not in roles.upper()
    checks = {
        "tables": require(schema, EXPECTED_TABLES, "tables"),
        "views": require(schema, EXPECTED_VIEWS, "views"),
        "functions": require(schema, EXPECTED_FUNCTIONS, "functions"),
        "triggers": require(schema, EXPECTED_TRIGGERS, "triggers"),
        "policies_present": "CREATE POLICY" in schema,
        "grants_present": "GRANT " in schema or "REVOKE " in schema,
        # A Supabase role-only dump may legitimately contain no custom roles after
        # reserved platform roles are removed. RESET ALL is the official dump
        # terminator and proves that the sanitized role export completed.
        "roles_dump_valid": (
            "CREATE ROLE" in roles or "ALTER ROLE" in roles or roles_are_sanitized
        ),
        "role_passwords_absent": "PASSWORD " not in roles.upper(),
        "data_statements_present": "COPY " in data or "INSERT INTO" in data,
    }
    required_boolean_checks = (
        "policies_present",
        "grants_present",
        "roles_dump_valid",
        "role_passwords_absent",
        "data_statements_present",
    )
    failed = [name for name in required_boolean_checks if not checks[name]]
    if failed:
        raise ValueError(f"backup verification failed checks: {', '.join(failed)}")

    manifest = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in files.items()
        },
        "checks": checks,
        "storage_note": "Database dump contains Storage metadata, not object bytes.",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "directory": str(directory), "files": manifest["files"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
