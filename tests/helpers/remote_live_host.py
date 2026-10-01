"""Manual live relay host used to verify ARCHEON PC/mobile commands."""

from __future__ import annotations

import signal
import time

from archeon.app import ArcheonApplication


def main() -> int:
    application = ArcheonApplication(port=0)
    application.start()
    try:
        session = application.auth.restore()
        if session is None or session.mode != "account":
            print("REMOTE_HOST_ERROR account_session_required", flush=True)
            return 2
        devices = application.handle_action("cloud.devices.list", {"_session_token": session.token})
        if not devices.get("ok"):
            print(f"REMOTE_HOST_ERROR {devices.get('error')}", flush=True)
            return 3
        print(f"REMOTE_HOST_READY devices={len(devices.get('devices', []))}", flush=True)
        stop = False

        def finish(*_args: object) -> None:
            nonlocal stop
            stop = True

        signal.signal(signal.SIGINT, finish)
        signal.signal(signal.SIGTERM, finish)
        deadline = time.monotonic() + 240
        while not stop and time.monotonic() < deadline:
            time.sleep(0.25)
        return 0
    finally:
        application.stop()


if __name__ == "__main__":
    raise SystemExit(main())
