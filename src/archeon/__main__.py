"""Command-line entry point for the runnable ARCHEON Core."""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from pathlib import Path
from threading import Event

from archeon.app import ArcheonApplication
from archeon.ui import DesktopHost, DesktopUnavailable


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    application = ArcheonApplication(
        data_dir=args.data_dir,
        port=args.port,
        console_log=args.console_log,
    )
    application.start()
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
            )
    except KeyboardInterrupt:
        pass
    except DesktopUnavailable as error:
        print(json.dumps({"event": "archeon.error", "error": str(error)}), flush=True)
        return 2
    finally:
        application.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
