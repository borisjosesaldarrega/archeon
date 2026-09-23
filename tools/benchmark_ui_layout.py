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

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/runtime-config.js":
            payload = b'window.ARCHEON_RUNTIME={token:"layout-probe",resumeSession:""};'
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


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
    media: rect('#music-panel'), command: rect('.command-console'),
    voice_button: rect('#voice-button'), voice_dot: rect('.voice-status-dot')
  };
  const shell = document.querySelector('#app-shell');
  media.classList.remove('active');
  media.setAttribute('aria-hidden', 'true');
  const collapsedBoxes = {orb:rect('.visualizer'), status:rect('.status-container')};
  shell.classList.add('input-hidden');
  const hiddenBoxes = {orb:rect('.visualizer'), status:rect('.status-container')};
  const hiddenGroupCenterY = (hiddenBoxes.orb.top + hiddenBoxes.status.bottom) / 2;
  const hiddenOrbCenterY = hiddenBoxes.orb.top + hiddenBoxes.orb.height / 2;
  shell.classList.remove('input-hidden');
  media.classList.add('active');
  media.setAttribute('aria-hidden', 'false');
  const settings = document.querySelector('#settings-dialog');
  settings.showModal();
  const settingsRect = rect('#settings-dialog form');
  settings.close();
  const launcher = document.querySelector('#launcher-dialog');
  launcher.showModal();
  const launcherRect = rect('#launcher-dialog form');
  launcher.close();
  document.querySelector('#settings-edit-layout').click();
  const editorRect = rect('#layout-editor');
  const elementSelect = document.querySelector('#layout-editor-element');
  elementSelect.value = 'assistant_name';
  elementSelect.dispatchEvent(new Event('change', {bubbles:true}));
  const colorInput = document.querySelector('#layout-editor-color');
  colorInput.value = '#a855f7';
  colorInput.dispatchEvent(new Event('input', {bubbles:true}));
  const previewColor = getComputedStyle(document.querySelector('#assistant-state')).color;
  const scaleInput = document.querySelector('#layout-editor-scale');
  scaleInput.value = '125';
  scaleInput.dispatchEvent(new Event('input', {bubbles:true}));
  const previewScale = getComputedStyle(document.querySelector('#assistant-state')).scale;
  elementSelect.value = 'command';
  elementSelect.dispatchEvent(new Event('change', {bubbles:true}));
  const widthInput = document.querySelector('#layout-editor-width');
  widthInput.value = '82';
  widthInput.dispatchEvent(new Event('input', {bubbles:true}));
  const previewWidth = document.querySelector('#command-form').getBoundingClientRect().width;
  document.querySelector('#layout-editor-close').click();
  const discardDialog = document.querySelector('#layout-confirm-dialog');
  const discardConfirmVisible = discardDialog.open;
  document.querySelector('#layout-confirm-accept').click();
  const inside = (box) => box.left >= -1 && box.top >= -1 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1;
  return {
    viewport:{width:innerWidth,height:innerHeight,devicePixelRatio}, boxes,
    geometry:{
      orb_center_x:boxes.orb.left + boxes.orb.width / 2,
      viewport_center_x:innerWidth / 2,
      orb_center_offset_x:(boxes.orb.left + boxes.orb.width / 2) - innerWidth / 2,
      hidden_group_center_y:hiddenGroupCenterY,
      hidden_orb_center_y:hiddenOrbCenterY,
      viewport_center_y:innerHeight / 2,
      hidden_group_offset_y:hiddenGroupCenterY - innerHeight / 2,
      hidden_orb_offset_y:hiddenOrbCenterY - innerHeight / 2
    },
    checks:{
      command_inside:inside(boxes.command), media_inside:inside(boxes.media),
      settings_inside:inside(settingsRect), launcher_inside:inside(launcherRect),
      layout_editor_inside:inside(editorRect),
      layout_preview_color:previewColor === 'rgb(168, 85, 247)',
      layout_preview_scale:Number.parseFloat(previewScale) > 1.24,
      layout_preview_width:previewWidth > innerWidth * .79 && previewWidth < innerWidth * .84,
      layout_discard_confirmation:discardConfirmVisible,
      layout_editor_closed:document.querySelector('#layout-editor').hidden && !document.body.classList.contains('layout-editing'),
      orb_status_clear:!overlaps(boxes.orb,boxes.status),
      status_media_clear:!overlaps(boxes.status,boxes.media),
      media_command_clear:!overlaps(boxes.media,boxes.command),
      orb_centered:Math.abs((boxes.orb.left + boxes.orb.width / 2) - innerWidth / 2) < 0.75,
      voice_dot_centered:
        Math.abs((boxes.voice_dot.left + boxes.voice_dot.width / 2) - (boxes.voice_button.left + boxes.voice_button.width / 2)) < 0.25 &&
        Math.abs((boxes.voice_dot.top + boxes.voice_dot.height / 2) - (boxes.voice_button.top + boxes.voice_button.height / 2)) < 0.25,
      input_toggle_keeps_orb_position:
        Math.abs(hiddenBoxes.orb.left-collapsedBoxes.orb.left) < .5 &&
        Math.abs(hiddenBoxes.orb.top-collapsedBoxes.orb.top) < .5,
      input_toggle_keeps_status_position:
        Math.abs(hiddenBoxes.status.left-collapsedBoxes.status.left) < .5 &&
        Math.abs(hiddenBoxes.status.top-collapsedBoxes.status.top) < .5
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
