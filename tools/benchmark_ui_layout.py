"""Exercise ARCHEON's real WebView layout at representative logical viewports."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "src" / "archeon" / "ui"
OUTPUT = ROOT / "benchmarks" / "ui-layout.json"
VIEWPORTS = (
    (1024, 600, "compact"),
    (1280, 720, "1600x900-at-125pct"),
    (1366, 768, "1366x768"),
    (1600, 900, "1600x900"),
    (1707, 960, "2560x1440-at-150pct"),
    (1920, 1080, "1920x1080"),
    (2560, 1440, "2560x1440"),
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


PROBE_JS = r"""
(() => {
  const rect = (selector) => {
    const node = document.querySelector(selector);
    const value = node.getBoundingClientRect();
    return {left:value.left, top:value.top, right:value.right, bottom:value.bottom, width:value.width, height:value.height};
  };
  const overlaps = (a, b) => a.right > b.left + 1 && a.left < b.right - 1 && a.bottom > b.top + 1 && a.top < b.bottom - 1;
  document.querySelector('#auth-shell').hidden = true;
  document.querySelector('#app-shell').hidden = false;
  document.body.classList.remove('auth-active');
  document.body.dataset.performance = 'eco';
  const media = document.querySelector('#music-panel');
  media.classList.add('active');
  media.setAttribute('aria-hidden', 'false');
  const boxes = {
    orb: rect('.visualizer'), status: rect('.status-container'),
    media: rect('#music-panel'), command: rect('.command-console')
  };
  const settings = document.querySelector('#settings-dialog');
  settings.showModal();
  const settingsRect = rect('#settings-dialog form');
  settings.close();
  const launcher = document.querySelector('#launcher-dialog');
  launcher.showModal();
  const launcherRect = rect('#launcher-dialog form');
  launcher.close();
  const inside = (box) => box.left >= -1 && box.top >= -1 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1;
  return {
    viewport:{width:innerWidth,height:innerHeight,devicePixelRatio}, boxes,
    checks:{
      command_inside:inside(boxes.command), media_inside:inside(boxes.media),
      settings_inside:inside(settingsRect), launcher_inside:inside(launcherRect),
      orb_status_clear:!overlaps(boxes.orb,boxes.status),
      status_media_clear:!overlaps(boxes.status,boxes.media),
      media_command_clear:!overlaps(boxes.media,boxes.command)
    }
  };
})()
"""


def main() -> int:
    handler = partial(QuietHandler, directory=str(UI_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, name="ui-layout-server", daemon=True)
    thread.start()
    window = webview.create_window(
        "ARCHEON UI layout probe",
        f"http://127.0.0.1:{server.server_port}/index.html",
        width=1024,
        height=600,
        min_size=(720, 480),
    )
    results: list[dict[str, object]] = []

    def probe() -> None:
        try:
            window.events.loaded.wait(5)
            for width, height, label in VIEWPORTS:
                window.resize(width, height)
                time.sleep(0.22)
                result = window.evaluate_js(PROBE_JS)
                result["target"] = {"width": width, "height": height, "label": label}
                result["ok"] = all(result["checks"].values())
                results.append(result)
        finally:
            window.destroy()

    try:
        webview.start(probe, debug=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scenario": "real_webview_responsive_layout",
        "results": results,
        "ok": len(results) == len(VIEWPORTS) and all(item["ok"] for item in results),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
