"""Benchmark offline queuing and the live Supabase/RLS transport boundary."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from archeon.sync import SupabaseSettingsSync


ROOT = Path(__file__).resolve().parents[1]
URL = "https://rcgipowzivogyqbuwzlv.supabase.co"
KEY = "sb_publishable_V0kfZlDv6HKNudCl_vObeQ_pRbDU1RU"


def main() -> int:
    envelope = {
        "version": 4,
        "updated_at": datetime.now(UTC).isoformat(),
        "settings": {"language": {"interface": "es"}, "assistant": {"wake_name": "Archeon"}},
    }
    with tempfile.TemporaryDirectory(prefix="archeon-sync-") as temporary:
        root = Path(temporary)
        offline = SupabaseSettingsSync("http://127.0.0.1:9", KEY, root, timeout=0.5)
        started = time.perf_counter()
        queued = offline.synchronize("11111111-1111-1111-1111-111111111111", "offline-jwt", envelope, envelope)
        offline_ms = (time.perf_counter() - started) * 1000
        pending_size = (root / "sync-pending.json").stat().st_size

    endpoint_started = time.perf_counter()
    endpoint_status = None
    rls_denied = False
    try:
        request = Request(f"{URL}/rest/v1/account_settings?select=user_id&limit=1", headers={"apikey": KEY})
        with urlopen(request, timeout=8) as response:
            endpoint_status = response.status
    except HTTPError as error:
        endpoint_status = error.code
        detail = json.loads(error.read().decode())
        rls_denied = detail.get("code") == "42501"
    online_ms = (time.perf_counter() - endpoint_started) * 1000
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "offline_queue_latency_ms": round(offline_ms, 3),
        "offline_queued": queued.get("queued"),
        "offline_pending_bytes": pending_size,
        "online_endpoint_latency_ms": round(online_ms, 3),
        "online_endpoint_status": endpoint_status,
        "online_rls_denied_without_user_jwt": rls_denied,
        "authenticated_roundtrip": "pending_final_controlled_email_validation",
    }
    target = ROOT / "benchmarks" / "sync.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if queued.get("queued") and rls_denied else 1


if __name__ == "__main__":
    raise SystemExit(main())
