"""Vision tool registration; model and capture remain fully on demand."""

from __future__ import annotations

import time
from difflib import SequenceMatcher
from typing import Any, Mapping
from pathlib import Path

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult
from archeon.desktop import WindowsDesktopObserver
from archeon.desktop.mouse import WindowsMouseFallback

from .manager import VisionComponentManager
from .provider import ArchiVisionProvider


VISION_OBSERVE_MANIFEST = ToolManifest(
    id="vision.observe_active", description="Analyze the active window visually only when structured evidence is insufficient",
    permissions=("desktop.observe",), risk=RiskLevel.READ_ONLY, timeout_seconds=300.0,
    resource_class="heavy_on_demand",
)
VISION_LOCATE_MANIFEST = ToolManifest(
    id="vision.locate_active", description="Visually locate a named control after structured lookup fails",
    permissions=("desktop.observe",), risk=RiskLevel.READ_ONLY, timeout_seconds=300.0,
    resource_class="heavy_on_demand",
)
VISION_CLICK_MANIFEST = ToolManifest(
    id="vision.click_active", description="Click a visually grounded control only after revalidation",
    permissions=("desktop.observe", "desktop.control"), risk=RiskLevel.LOW, timeout_seconds=300.0,
    resource_class="heavy_on_demand",
)
VISION_FILE_MANIFEST = ToolManifest(
    id="vision.analyze_file", description="Analyze one explicit attached image on demand",
    permissions=("filesystem.read",), risk=RiskLevel.READ_ONLY, timeout_seconds=300.0,
    resource_class="heavy_on_demand",
)


def _capture_observation(provider: ArchiVisionProvider, arguments: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    from PIL import ImageGrab

    observer = WindowsDesktopObserver()
    window = observer.active_window()
    expected = int(arguments.get("window_handle", 0) or 0)
    if expected and expected != window.handle:
        raise RuntimeError("target_window_changed")
    capture_started = time.perf_counter()
    image = ImageGrab.grab(bbox=window.bounds, all_screens=True)
    capture_ms = (time.perf_counter() - capture_started) * 1000
    try:
        encoded, size, preprocessing_ms = provider.preprocess(
            image, max_side=int(arguments.get("max_side", 960)),
        )
    finally:
        image.close()
    observation = provider.analyze(
        encoded, prompt=str(arguments.get("prompt", "Analyze visible errors and relevant controls.")),
        image_size=size,
    ).public()
    observation["window"] = window.public()
    observation["metrics"].update({
        "capture_ms": round(capture_ms, 3), "preprocessing_ms": round(preprocessing_ms, 3),
        "screenshot_persisted": False,
    })
    return window, observation


def _select_control(observation: Mapping[str, Any], target: str) -> dict[str, Any]:
    query = " ".join(target.casefold().split())
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in observation.get("controls", []):
        if not isinstance(item, dict) or item.get("grounding_valid") is False or "bounds" not in item:
            continue
        label = str(item.get("label") or item.get("text") or item.get("name") or "")
        normalized = " ".join(label.casefold().split())
        if normalized == query:
            score = 1.0
        elif query and (query in normalized.split() or normalized in query.split()):
            score = 0.95
        else:
            score = SequenceMatcher(None, query, normalized).ratio()
        candidates.append((score, dict(item)))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    if not candidates or candidates[0][0] < 0.82 or float(observation.get("confidence", 0.0)) < 0.70:
        raise RuntimeError("visual_grounding_confidence_too_low")
    selected = candidates[0][1]
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 0.05:
        raise RuntimeError("visual_target_ambiguous")
    return selected


def _absolute_bounds(window: Any, normalized: list[float]) -> tuple[int, int, int, int]:
    left, top, right, bottom = window.bounds
    width, height = right - left, bottom - top
    return (
        left + round(normalized[0] * width), top + round(normalized[1] * height),
        left + round(normalized[2] * width), top + round(normalized[3] * height),
    )


class VisionObserveTool:
    manifest = VISION_OBSERVE_MANIFEST

    def __init__(self, provider: ArchiVisionProvider) -> None:
        self.provider = provider
        self.observer = WindowsDesktopObserver()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        window, observation = _capture_observation(self.provider, arguments)
        return ToolResult(
            True, observation,
            evidence={"window_handle": window.handle, "confidence": observation["confidence"],
                      "screenshot_persisted": False},
        )

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("window_handle") and result.data.get("window_summary"))


class VisionFileTool:
    manifest = VISION_FILE_MANIFEST

    def __init__(self, provider: ArchiVisionProvider) -> None:
        self.provider = provider

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        from PIL import Image

        path = Path(str(arguments.get("path", ""))).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("image_path_or_size_invalid")
        with Image.open(path) as image:
            encoded, size, preprocessing_ms = self.provider.preprocess(
                image.convert("RGB"), max_side=int(arguments.get("max_side", 1280)),
            )
        observation = self.provider.analyze(
            encoded, prompt=str(arguments.get("prompt") or "Describe only what is verifiably visible in this image."),
            image_size=size,
        ).public()
        observation["path"] = str(path)
        observation["metrics"] = {**observation.get("metrics", {}), "preprocessing_ms": round(preprocessing_ms, 3), "source_persisted": True}
        return ToolResult(True, observation, evidence={"file_exists": True, "confidence": observation["confidence"]})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("file_exists") and result.data.get("window_summary"))


class VisionLocateTool:
    manifest = VISION_LOCATE_MANIFEST

    def __init__(self, provider: ArchiVisionProvider) -> None:
        self.provider = provider

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        target = str(arguments.get("name", "")).strip()
        if not target:
            raise ValueError("visual_target_required")
        window, observation = _capture_observation(self.provider, {
            **dict(arguments), "prompt": f"Locate the visible control named {target!r}. Do not guess its bounds.",
        })
        selected = _select_control(observation, target)
        bounds = _absolute_bounds(window, selected["bounds"])
        return ToolResult(True, {"element": target, "bounds": bounds, "window": window.public(),
                                "confidence": observation["confidence"], "method": "archi_vision",
                                "screenshot_persisted": False},
                          evidence={"window_handle": window.handle, "grounding_valid": True,
                                    "confidence": observation["confidence"]})

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("grounding_valid") and float(result.evidence.get("confidence", 0)) >= 0.70)


class VisionClickTool:
    manifest = VISION_CLICK_MANIFEST

    def __init__(self, provider: ArchiVisionProvider) -> None:
        self.provider = provider
        self.observer = WindowsDesktopObserver()
        self.mouse = WindowsMouseFallback()

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        target = str(arguments.get("name", "")).strip()
        if not target:
            raise ValueError("visual_target_required")
        self.provider.invalidate_cache()
        window, observation = _capture_observation(self.provider, {
            **dict(arguments), "prompt": f"Locate the visible control named {target!r}. Do not guess its bounds.",
        })
        selected = _select_control(observation, target)
        bounds = _absolute_bounds(window, selected["bounds"])
        before = self.observer.observe_active(include_screenshot_hash=True)["state_hash"]
        action = self.mouse.perform("left_click", window_handle=window.handle,
                                    observed_window_bounds=window.bounds, target_bounds=bounds,
                                    movement_mode=str(arguments.get("movement_mode", "normal")),
                                    show_cursor=bool(arguments.get("show_cursor", True)),
                                    reduce_motion=bool(arguments.get("reduce_motion", False)))
        time.sleep(0.25)
        after = self.observer.observe_active(include_screenshot_hash=True)["state_hash"]
        self.provider.invalidate_cache()
        changed = before != after
        return ToolResult(changed, {**action, "element": target, "confidence": observation["confidence"],
                                   "before_hash": before, "after_hash": after, "method": "archi_vision"},
                          error=None if changed else "visual_action_not_verified",
                          evidence={"target_revalidated": True, "changed_state": changed,
                                    "confidence": observation["confidence"]}, changed_state=changed)

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.evidence.get("target_revalidated") and result.evidence.get("changed_state")
                    and float(result.evidence.get("confidence", 0)) >= 0.70)


class VisionAgentEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine, components: VisionComponentManager, provider: ArchiVisionProvider | None) -> None:
        super().__init__("vision_agent")
        self.tools = tools
        self.components = components
        self.provider = provider

    def _start(self) -> None:
        if self.provider is not None:
            self.tools.register(VISION_FILE_MANIFEST, lambda: VisionFileTool(self.provider))
            self.tools.register(VISION_OBSERVE_MANIFEST, lambda: VisionObserveTool(self.provider))
            self.tools.register(VISION_LOCATE_MANIFEST, lambda: VisionLocateTool(self.provider))
            self.tools.register(VISION_CLICK_MANIFEST, lambda: VisionClickTool(self.provider))

    def _stop(self) -> None:
        for manifest in (VISION_FILE_MANIFEST, VISION_CLICK_MANIFEST, VISION_LOCATE_MANIFEST, VISION_OBSERVE_MANIFEST):
            self.tools.unregister(manifest.id)
        if self.provider is not None:
            self.provider.unload()
