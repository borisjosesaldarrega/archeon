"""Lightweight goal-to-capability routing before tool selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from archeon.core.tools import ToolManifest
from archeon.understanding.intent_guard import has_unnegated, is_current_information_request


class Capability(StrEnum):
    CONVERSATION = "conversation"
    SEARCH = "search"
    BROWSER = "browser"
    FILES = "files"
    DOCUMENTS = "documents"
    ARTIFACTS = "artifacts"
    PROGRAMMING = "programming"
    TERMINAL = "terminal"
    DESKTOP = "desktop"
    VISION = "vision"
    MEDIA = "media"
    MUSIC = "music"
    DEVICE = "device"
    ARCHIVES = "archives"
    KNOWLEDGE = "knowledge"
    MEMORY = "memory"
    CLOUD = "future_cloud"
    EXTENSIONS = "future_extensions"


PREFIX_CAPABILITY = {
    "search": Capability.SEARCH, "browser": Capability.BROWSER, "files": Capability.FILES,
    "documents": Capability.DOCUMENTS, "artifacts": Capability.ARTIFACTS,
    "programming": Capability.PROGRAMMING, "terminal": Capability.TERMINAL,
    "desktop": Capability.DESKTOP, "vision": Capability.VISION, "media": Capability.MEDIA,
    "device": Capability.DEVICE, "archives": Capability.ARCHIVES,
}


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    goal: str
    capabilities: tuple[Capability, ...]
    reasons: dict[str, str]
    source_required: bool
    control_requested: bool
    future_only: tuple[Capability, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "capabilities": [item.value for item in self.capabilities],
            "reasons": dict(self.reasons), "source_required": self.source_required,
            "control_requested": self.control_requested,
            "future_only": [item.value for item in self.future_only],
        }


class CapabilityRouter:
    """Classifies one objective; it never executes tools or grants permissions."""

    RULES: tuple[tuple[Capability, str, str], ...] = (
        (Capability.SEARCH, r"\b(busca|investiga|noticias|actualidad|search|research)\b", "current or sourced information"),
        (Capability.BROWSER, r"\b(navegador|web|sitio|p[aá]gina|url|browser|internet|scroll)\b", "web navigation or DOM interaction"),
        (Capability.FILES, r"\b(archivo|carpeta|ruta|descargas|file|folder)\b", "local filesystem object"),
        (Capability.DOCUMENTS, r"\b(documento|word|docx|pdf|texto|document)\b", "document reading or transformation"),
        (Capability.ARTIFACTS, r"\b(crea|genera|informe|excel|xlsx|powerpoint|pptx|csv|json|presentaci[oó]n|reporte)\b", "structured deliverable requested"),
        (Capability.ARCHIVES, r"\b(zip|7z|rar|tar|comprime|descomprime|archivo comprimido)\b", "archive operation"),
        (Capability.PROGRAMMING, r"\b(c[oó]digo|proyecto|programa|bug|git|pruebas?|programming|code)\b", "software project work"),
        (Capability.TERMINAL, r"\b(terminal|powershell|comando|script|consola)\b", "bounded command execution"),
        (Capability.DESKTOP, r"\b(pantalla|ventana|clic|pulsa|escritorio|usa mi pc|mouse|teclado)\b", "desktop observation or control"),
        (Capability.VISION, r"\b(mira|ves|visual|imagen|captura|pantalla)\b", "visual perception may be required after structured methods"),
        (Capability.MEDIA, r"\b(audio|v[ií]deo|reproductor|media)\b", "media operation"),
        (Capability.MUSIC, r"\b(m[uú]sica|canci[oó]n|artista|playlist)\b", "music discovery or playback"),
        (Capability.DEVICE, r"\b(micr[oó]fono|altavoz|monitor|dispositivo|volumen)\b", "device-specific setting"),
        (Capability.MEMORY, r"\b(recuerda|memoria|contexto anterior|preferencia)\b", "persistent or recent context"),
        (Capability.EXTENSIONS, r"\b(plugin|extensi[oó]n|\.arx)\b", "future extension contract"),
        (Capability.CLOUD, r"\b(cloud|nube|m[oó]vil|sincroniza en l[ií]nea)\b", "future cloud contract"),
    )

    def route(self, goal: str, *, attachment_names: Iterable[str] = ()) -> CapabilityRoute:
        normalized = " ".join(goal.casefold().split())
        ordered: list[Capability] = []
        reasons: dict[str, str] = {}
        for capability, pattern, reason in self.RULES:
            if re.search(pattern, normalized):
                ordered.append(capability); reasons[capability.value] = reason
        if is_current_information_request(normalized):
            self._add(ordered, reasons, Capability.SEARCH, "explicitly current information")
        suffixes = {name.rsplit(".", 1)[-1].casefold() for name in attachment_names if "." in name}
        if suffixes & {"docx", "pdf", "txt", "md"}:
            self._add(ordered, reasons, Capability.DOCUMENTS, "document attachment")
        if suffixes & {"xlsx", "pptx", "csv", "json", "html"}:
            self._add(ordered, reasons, Capability.ARTIFACTS, "structured artifact attachment")
        if suffixes & {"zip", "7z", "rar", "tar", "gz"}:
            self._add(ordered, reasons, Capability.ARCHIVES, "archive attachment")
        if not ordered:
            ordered.append(Capability.CONVERSATION); reasons[Capability.CONVERSATION.value] = "direct conversational response"
        if Capability.SEARCH in ordered or Capability.BROWSER in ordered:
            self._add(ordered, reasons, Capability.KNOWLEDGE, "ground claims in retrieved sources")
        future = tuple(item for item in ordered if item in {Capability.CLOUD, Capability.EXTENSIONS})
        return CapabilityRoute(
            goal=goal.strip(), capabilities=tuple(ordered), reasons=reasons,
            source_required=Capability.SEARCH in ordered or Capability.BROWSER in ordered,
            control_requested=has_unnegated(
                r"\b(?:usa mi pc|pulsa|haz clic|crea|genera|"
                r"(?:corrige|arregla|edita)\b.{0,36}\b(?:archivo|documento|proyecto|c[oó]digo|pc|ventana|app))\b",
                normalized,
            ),
            future_only=future,
        )

    @staticmethod
    def _add(ordered: list[Capability], reasons: dict[str, str], capability: Capability, reason: str) -> None:
        if capability not in ordered:
            ordered.append(capability); reasons[capability.value] = reason

    @staticmethod
    def available_tools(route: CapabilityRoute, manifests: Iterable[ToolManifest]) -> dict[str, list[str]]:
        selected = {item.value: [] for item in route.capabilities}
        for manifest in manifests:
            capability = PREFIX_CAPABILITY.get(manifest.id.split(".", 1)[0])
            if capability and capability.value in selected:
                selected[capability.value].append(manifest.id)
        return selected
