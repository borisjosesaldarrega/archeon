"""Content-driven artifact planning and honest post-render quality review.

The module is deliberately dependency-light.  Heavy renderers remain tool
providers and only pass compact evidence into these engines on demand.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


QUALITY_DIMENSIONS = (
    "instruction_compliance", "content_quality", "natural_language",
    "visual_design", "readability", "hierarchy", "layout",
    "media_relevance", "editability", "technical_validity", "accessibility",
    "evidence_integrity", "format_specific_quality",
)


class ArtifactProfile(StrEnum):
    ASSIGNMENT = "assignment"
    SIMPLE_STUDENT_ASSIGNMENT = "simple_student_assignment"
    RESEARCH_PAPER = "research_paper"
    TECHNICAL_REPORT = "technical_report"
    BUSINESS_REPORT = "business_report"
    FORMAL_LETTER = "formal_letter"
    RESUME = "resume"
    MANUAL = "manual"
    TUTORIAL = "tutorial"
    PORTFOLIO = "portfolio"
    PRESENTATION = "presentation"
    VISUAL_PRESENTATION = "visual_presentation"
    INFOGRAPHIC = "infographic"
    SPREADSHEET = "spreadsheet"
    DASHBOARD = "dashboard"
    WEB_PROJECT = "web_project"


@dataclass(frozen=True, slots=True)
class RequirementPlan:
    deliverables: tuple[str, ...]
    formats: tuple[str, ...]
    required_sections: tuple[str, ...]
    questions: tuple[str, ...]
    visual_requirements: tuple[str, ...]
    evidence_required: bool
    sources_required: bool
    tone: str
    student_level: str
    missing_required_info: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]: return asdict(self)


class AssignmentIntelligence:
    """Extracts a compact multi-artifact requirement plan without personal-data guesses."""

    FORMAT_PATTERNS = {"docx": r"\b(?:word|docx)\b", "xlsx": r"\b(?:excel|xlsx|exel)\b", "pptx": r"\b(?:powerpoint|pptx|presentaci[oó]n)\b", "pdf": r"\bpdf\b", "zip": r"\bzip\b"}

    def plan(self, instruction: str, *, known_user_name: str = "") -> RequirementPlan:
        value = re.sub(r"\s+", " ", instruction).strip(); folded = value.casefold()
        formats = tuple(name for name, pattern in self.FORMAT_PATTERNS.items() if re.search(pattern, folded))
        sections = tuple(match.group(1).strip() for match in re.finditer(r"(?:secci[oó]n|apartado)\s+([^,.;]+)", value, re.I))
        questions = tuple(match.group(0).strip() for match in re.finditer(r"[^?¿]{3,}\?", value))
        visuals = tuple(label for label, pattern in (("screenshots", r"capturas?"), ("diagrams", r"diagramas?"), ("charts", r"gr[aá]fic[oa]s?"), ("photos", r"fotos? reales?"), ("images", r"im[aá]genes?")) if re.search(pattern, folded))
        missing: list[str] = []
        if re.search(r"(?:mi nombre|nombre del estudiante)", folded) and not known_user_name.strip(): missing.append("authorized_user_name")
        tone = "simple_student" if re.search(r"(?:tarea normal|no.*super profesional|simple)", folded) else "context_appropriate"
        level = "unspecified"
        match = re.search(r"(?:nivel|curso|semestre)\s*[:=]?\s*([^,.;]+)", value, re.I)
        if match: level = match.group(1).strip()
        deliverables = tuple(f"artifact:{name}" for name in formats) or ("artifact:unspecified",)
        return RequirementPlan(deliverables, formats, sections, questions, visuals, bool(re.search(r"(?:evidencia|captura|demuestra)", folded)), bool(re.search(r"(?:fuentes?|bibliograf|referencias?)", folded)), tone, level, tuple(missing))


@dataclass(frozen=True, slots=True)
class QualityIssue:
    dimension: str
    code: str
    message: str
    severity: str = "medium"
    repair: str = ""

    def public(self) -> dict[str, str]: return asdict(self)


@dataclass(frozen=True, slots=True)
class QualityReport:
    artifact: str
    scores: dict[str, float]
    issues: tuple[QualityIssue, ...]
    strengths: tuple[str, ...] = ()
    remaining_issues: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        critical = any(item.severity == "critical" for item in self.issues)
        return not critical and self.scores.get("technical_validity", 0.0) == 1.0 and self.scores.get("instruction_compliance", 0.0) >= 0.8

    def public(self) -> dict[str, Any]:
        return {"artifact": self.artifact, "passed": self.passed, "scores": self.scores, "issues": [item.public() for item in self.issues], "strengths": list(self.strengths), "remaining_issues": list(self.remaining_issues)}


class ArtifactQualityEngine:
    """Scores supplied evidence; it never assigns success by artifact name."""

    @staticmethod
    def _ratio(value: Any, fallback: float = 0.0) -> float:
        if isinstance(value, bool): return 1.0 if value else 0.0
        if isinstance(value, (int, float)): return round(max(0.0, min(1.0, float(value))), 3)
        return fallback

    def review(self, artifact: str, evidence: Mapping[str, Any]) -> QualityReport:
        scores = {name: self._ratio(evidence.get(name), 0.5) for name in QUALITY_DIMENSIONS}
        issues: list[QualityIssue] = []
        for name, score in scores.items():
            if score < 0.5:
                issues.append(QualityIssue(name, f"weak_{name}", f"{name} remains materially weak ({score:.2f}).", "high" if name in {"technical_validity", "instruction_compliance", "evidence_integrity"} else "medium", f"Repair the specific {name.replace('_', ' ')} evidence and render again."))
        if evidence.get("paragraph_walls"):
            issues.append(QualityIssue("readability", "paragraph_walls", "Visible content contains paragraph walls.", repair="Shorten visible copy and move supporting detail to notes."))
        if evidence.get("repetitive_layout_ratio", 0) > 0.6:
            issues.append(QualityIssue("visual_design", "template_repetition", "Too many pages repeat the same composition.", repair="Choose content-driven slide/page intents and vary silhouettes."))
        if evidence.get("thematic_visuals", 0) < evidence.get("minimum_thematic_visuals", 0):
            issues.append(QualityIssue("media_relevance", "insufficient_thematic_visuals", "The artifact lacks enough visuals that explain the subject.", repair="Add a relevant diagram, illustration, chart, screenshot, or licensed image."))
        if evidence.get("print_columns_cut"):
            issues.append(QualityIssue("format_specific_quality", "print_columns_cut", "Spreadsheet columns are split or cut in print output.", "high", "Set print area, orientation and fit-to-width, then render every PDF page."))
        if evidence.get("orphan_chart"):
            issues.append(QualityIssue("layout", "orphan_chart", "A chart is isolated from the summary it explains.", repair="Keep the chart and summary in one print region/page."))
        return QualityReport(artifact, scores, tuple(issues), tuple(str(item) for item in evidence.get("strengths", ())), tuple(str(item) for item in evidence.get("remaining_issues", ())))


@dataclass(frozen=True, slots=True)
class DesignIntent:
    profile: ArtifactProfile
    tone: str
    density: str
    objectives: tuple[str, ...]
    avoid: tuple[str, ...]

    def public(self) -> dict[str, Any]: return asdict(self)


class DesignIntentEngine:
    """Turns colloquial visual criticism into concrete design objectives."""

    def interpret(self, request: str, *, profile: ArtifactProfile = ArtifactProfile.ASSIGNMENT) -> DesignIntent:
        value = re.sub(r"\s+", " ", request.casefold()).strip(); objectives: list[str] = []; avoid: list[str] = []
        if re.search(r"(?:fea|primer semestre|hazla bien|bonit[oa])", value): objectives += ["strengthen_hierarchy", "improve_spacing", "polish_interactions"]
        if re.search(r"(?:puro cuadrito|plantilla|muy ia|parece ia)", value): objectives += ["content_driven_layout", "vary_composition"]; avoid += ["repetitive_cards", "decorative_symmetry", "generic_gradients"]
        if re.search(r"(?:puro texto|pon(?:le)? (?:imagen(?:es)?|cosas del tema)|más visual)", value): objectives += ["add_thematic_visuals", "reduce_visible_text"]
        if re.search(r"(?:no tan cargado|simple|tarea normal|no.*super profesional)", value): objectives += ["student_appropriate", "reduce_decoration"]
        if re.search(r"(?:serio|profesional)", value): objectives += ["restrained_palette", "consistent_grid", "evidence_forward"]
        if re.search(r"(?:excel|exel).*(?:pdf|parte|imprime)", value): objectives += ["repair_print_layout", "keep_columns_together", "avoid_orphan_chart"]
        if not objectives: objectives = ["context_appropriate", "readable", "coherent"]
        density = "light" if "reduce_visible_text" in objectives or "reduce_decoration" in objectives else "balanced"
        tone = "simple_student" if "student_appropriate" in objectives else "professional"
        return DesignIntent(profile, tone, density, tuple(dict.fromkeys(objectives)), tuple(dict.fromkeys(avoid)))


@dataclass(frozen=True, slots=True)
class VisualAsset:
    asset: str
    kind: str
    purpose: str
    evidence: bool
    source: str
    license_status: str
    author: str = ""
    url: str = ""
    retrieval_date: str = ""

    def public(self) -> dict[str, Any]: return asdict(self)


class VisualAssetRouter:
    def choose(self, purpose: str, *, requires_real_photo: bool = False, evidence: bool = False, offline: bool = True) -> str:
        value = purpose.casefold()
        if evidence: return "real_screenshot_or_source_evidence"
        if requires_real_photo: return "licensed_external_photo"
        if any(word in value for word in ("timeline", "flow", "process", "architecture", "comparison")): return "generated_svg"
        if any(word in value for word in ("trend", "distribution", "ranking", "data")): return "generated_chart"
        if any(word in value for word in ("embry", "anatom", "scientific")): return "generated_educational_illustration"
        return "generated_iconography" if offline else "licensed_external_image"

    @staticmethod
    def relevant(asset: VisualAsset) -> bool:
        return bool(asset.purpose.strip() and asset.purpose.casefold() not in {"decorate", "decoration", "looks nice"})


@dataclass(frozen=True, slots=True)
class DiagramPlan:
    kind: str
    message: str
    nodes: tuple[str, ...]
    connectors: tuple[tuple[int, int], ...]
    editable: bool = True

    def public(self) -> dict[str, Any]: return asdict(self)


class DiagramEngine:
    TYPES = frozenset({"timeline", "flowchart", "cycle", "process", "comparison", "architecture", "hierarchy", "relationship", "before_after", "annotated_schematic"})

    def plan(self, kind: str, message: str, nodes: Iterable[str], connectors: Iterable[tuple[int, int]] = ()) -> DiagramPlan:
        normalized = kind.casefold().replace("/", "_")
        if normalized not in self.TYPES: raise ValueError("unsupported_diagram_type")
        items = tuple(str(item).strip() for item in nodes if str(item).strip())
        if len(items) < 2: raise ValueError("diagram_requires_multiple_nodes")
        edges = tuple(connectors) or tuple((index, index + 1) for index in range(len(items) - 1))
        if any(start < 0 or end < 0 or start >= len(items) or end >= len(items) for start, end in edges): raise ValueError("diagram_connector_out_of_range")
        return DiagramPlan(normalized, message.strip(), items, edges)


@dataclass(frozen=True, slots=True)
class PrintLayoutPlan:
    print_area: str
    paper_size: str = "A4"
    orientation: str = "landscape"
    fit_to_width: int = 1
    fit_to_height: int = 1
    repeat_header: str = ""
    center_horizontally: bool = True
    margins_inches: tuple[float, float, float, float] = (0.35, 0.35, 0.45, 0.45)

    def public(self) -> dict[str, Any]: return asdict(self)


class PrintLayoutEngine:
    def plan(self, *, used_columns: int, used_rows: int, print_area: str, header_row: int | None = None, chart_beside_summary: bool = False) -> PrintLayoutPlan:
        orientation = "landscape" if used_columns > 6 or chart_beside_summary else "portrait"
        fit_height = 1 if used_rows <= 45 else 0
        return PrintLayoutPlan(print_area, orientation=orientation, fit_to_height=fit_height, repeat_header=f"${header_row}:${header_row}" if header_row else "")

    @staticmethod
    def review_pdf(*, pages: int, columns_cut: bool, orphan_chart: bool, blank_pages: int, tiny_scale: bool) -> dict[str, Any]:
        return {"pages": pages, "columns_cut": columns_cut, "orphan_chart": orphan_chart, "blank_pages": blank_pages, "tiny_scale": tiny_scale, "passed": pages > 0 and not any((columns_cut, orphan_chart, blank_pages, tiny_scale))}


class InfographicEngine:
    def plan(self, subject: str, phases: Iterable[str]) -> dict[str, Any]:
        items = tuple(phases)
        return {"subject": subject, "layout": "spatial_storytelling_timeline", "phases": items, "minimum_thematic_visuals": max(3, min(len(items), 9)), "label_schematic_visuals": True, "require_visible_sources": True}


class WebDesignEngine:
    def plan(self, goal: str, flows: Iterable[str]) -> dict[str, Any]:
        return {"goal": goal, "flows": tuple(flows), "components": ("header", "composer", "filters", "task_list", "empty_state", "status_footer"), "breakpoints": (480, 768, 1100), "states": ("hover", "focus", "pressed", "disabled", "empty", "invalid", "completed"), "accessibility": ("landmarks", "labels", "keyboard", "visible_focus", "contrast", "reduced_motion")}


@dataclass(frozen=True, slots=True)
class PreviewPolicy:
    isolated_origin: bool = True
    filesystem_access: bool = False
    external_navigation: bool = False
    execute_unknown_javascript: bool = False
    csp: str = "default-src 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'"


class ArtifactPreviewSurface:
    """Architecture contract only; it does not bypass host Browser policies."""
    def policy(self) -> PreviewPolicy: return PreviewPolicy()
    def may_preview(self, root: str | Path, entrypoint: str | Path) -> bool:
        base = Path(root).expanduser().resolve(); target = Path(entrypoint).expanduser().resolve()
        return target.is_file() and target.suffix.casefold() in {".html", ".htm"} and (target == base or base in target.parents)


class ImageGenerationProvider(Protocol):
    def generate(self, prompt: str) -> VisualAsset: ...


class ImageEditProvider(Protocol):
    def edit(self, source: str, instruction: str) -> VisualAsset: ...


class CreativeAssetEngine:
    def __init__(self, image_provider: ImageGenerationProvider | None = None, edit_provider: ImageEditProvider | None = None) -> None:
        self.image_provider = image_provider; self.edit_provider = edit_provider

    def capabilities(self) -> dict[str, bool]:
        return {"svg": True, "diagram": True, "chart": True, "procedural": True, "image_generation": self.image_provider is not None, "image_editing": self.edit_provider is not None}
