"""Command-line entry point for the runnable ARCHEON Core."""

from __future__ import annotations

import argparse
import ctypes
import json
import time
import webbrowser
from pathlib import Path
from threading import Event

from archeon.app import ArcheonApplication
from archeon.ui import DesktopHost, DesktopUnavailable


class SingleInstance:
    """Windows named mutex that prevents duplicated ARCHEON runtimes."""

    def __init__(self) -> None:
        self._handle = None

    def acquire(self) -> bool:
        if __import__("os").name != "nt":
            return True
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\ARCHEON.Core.SingleInstance")
        if not handle:
            return False
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archeon")
    parser.add_argument("--headless", action="store_true", help="Run Core and UI server without a window")
    parser.add_argument("--browser", action="store_true", help="Open the local UI in the default browser")
    parser.add_argument("--ghost", action="store_true", help="Start with the independent Ghost window")
    parser.add_argument("--auto-exit", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--console-log", action="store_true")
    parser.add_argument("--benchmark-music", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--benchmark-guest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--benchmark-launcher", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--benchmark-radial", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--benchmark-background", choices=("image", "video"), help=argparse.SUPPRESS)
    parser.add_argument("--allow-multiple", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    instance = SingleInstance()
    if not args.allow_multiple and not instance.acquire():
        return 0
    application = ArcheonApplication(
        data_dir=args.data_dir,
        port=args.port,
        console_log=args.console_log,
    )
    application.start()
    if args.benchmark_background:
        visual = (
            Path(__file__).resolve().parent / "ui" / "logo_asitente.png"
            if args.benchmark_background == "image"
            else Path(__file__).resolve().parents[2] / "assets" / "ARCHEON.mp4"
        )
        application.configuration.update_settings({"appearance": {
            "background_type": args.benchmark_background,
            "background_path": str(visual),
        }})
    launcher_ms = None
    launcher_count = None
    if args.benchmark_launcher:
        launcher_started = time.perf_counter()
        launcher_count = len(application.launcher.refresh(force=True))
        launcher_ms = (time.perf_counter() - launcher_started) * 1000
    print(
        json.dumps(
            {
                "event": "archeon.ready",
                "url": application.ui_server.url,
                "startup_ms": round(application.startup_ms, 3),
                "pid": __import__("os").getpid(),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    if launcher_ms is not None:
        print(json.dumps({
            "event": "archeon.benchmark.launcher", "items": launcher_count,
            "scan_ms": round(launcher_ms, 3),
        }, separators=(",", ":")), flush=True)
    try:
        if args.headless:
            stopped = Event()
            stopped.wait(args.auto_exit)
        elif args.browser:
            webbrowser.open(f"{application.ui_server.url}/?token={application.ui_server.token}")
            if args.auto_exit:
                time.sleep(args.auto_exit)
            else:
                Event().wait()
        else:
            if args.benchmark_music and args.ghost:
                benchmark_result = application.handle_action("media.play")
                print(
                    json.dumps(
                        {"event": "archeon.benchmark.music", "ok": benchmark_result.get("ok", False)},
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
            host = DesktopHost(
                application.events,
                base_url=application.ui_server.url,
                token=application.ui_server.token,
                config=application.configuration.config,
                action_handler=application.handle_action,
                media_status_handler=application.media.status,
                artwork_handler=application.media.artwork,
            )
            host.run(
                initial_mode="ghost" if args.ghost else "main",
                auto_exit_seconds=args.auto_exit,
                benchmark_music=args.benchmark_music,
                benchmark_guest=args.benchmark_guest,
                benchmark_radial=args.benchmark_radial,
            )
    except KeyboardInterrupt:
        pass
    except DesktopUnavailable as error:
        print(json.dumps({"event": "archeon.error", "error": str(error)}), flush=True)
        return 2
    finally:
        application.stop()
        instance.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
