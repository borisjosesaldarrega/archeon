"""Strict, evidence-led advanced artifact quality and visual planning engines."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping


QUALITY_DIMENSIONS_V2 = (
    "technical_validity", "requirement_compliance", "content_quality",
    "visual_quality", "design_maturity", "media_relevance", "accessibility",
    "editability", "consistency",
)


class QualityGate(StrEnum):
    PASS = "PASS"
    PASS_WITH_NOTES = "PASS_WITH_NOTES"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class QualitySubcheck:
    name: str
    status: str
    evidence: str = ""
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class QualityReviewV2:
    artifact: str
    gate: QualityGate
    scores: dict[str, float]
    subchecks: tuple[QualitySubcheck, ...]
    issues: tuple[str, ...]
    weakest_aspects: tuple[str, ...]
    consistency_repairs: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.gate in {QualityGate.PASS, QualityGate.PASS_WITH_NOTES}

    def public(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact, "gate": self.gate.value, "passed": self.passed,
            "scores": self.scores, "subchecks": [asdict(item) for item in self.subchecks],
            "issues": list(self.issues), "weakest_aspects": list(self.weakest_aspects),
            "consistency_repairs": list(self.consistency_repairs),
        }


class QualityConsistencyValidator:
    """Prevents an optimistic overall result from contradicting failed evidence."""

    _ORDER = {
        QualityGate.PASS: 0, QualityGate.PASS_WITH_NOTES: 1,
        QualityGate.NEEDS_IMPROVEMENT: 2, QualityGate.FAIL: 3, QualityGate.BLOCKED: 4,
    }

    def validate(self, gate: QualityGate, subchecks: Iterable[QualitySubcheck]) -> tuple[QualityGate, tuple[str, ...]]:
        checks = tuple(subchecks); repairs: list[str] = []
        failed = [item for item in checks if item.status == "FAIL"]
        blocked = [item for item in checks if item.status == "BLOCKED"]
        unexplained = [item for item in failed if not item.explanation.strip()]
        required_failure = [item for item in failed if item.name in {"technical_validity", "requirement_compliance", "consistency"}]
        target = gate
        if blocked:
            target = QualityGate.BLOCKED
            repairs.append("overall_downgraded_due_to_blocked_subcheck")
        elif required_failure:
            target = QualityGate.FAIL
            repairs.append("overall_downgraded_due_to_required_failure")
        elif failed and gate in {QualityGate.PASS, QualityGate.PASS_WITH_NOTES}:
            target = QualityGate.NEEDS_IMPROVEMENT
            repairs.append("overall_downgraded_due_to_failed_subcheck")
        if unexplained:
            target = QualityGate.FAIL
            repairs.append("failed_subcheck_requires_explanation")
        return target, tuple(repairs)


class ArtifactQualityEngineV2:
    """Strict scoring: technical correctness never implies design quality."""

    def __init__(self) -> None:
        self.consistency = QualityConsistencyValidator()

    @staticmethod
    def _score(value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return round(max(0.0, min(1.0, float(value))), 3)
        return None

    def review(self, artifact: str, evidence: Mapping[str, Any]) -> QualityReviewV2:
        missing = [name for name in QUALITY_DIMENSIONS_V2 if self._score(evidence.get(name)) is None]
        scores = {name: self._score(evidence.get(name)) or 0.0 for name in QUALITY_DIMENSIONS_V2}
        subchecks = tuple(
            QualitySubcheck(
                name,
                "BLOCKED" if name in missing else "PASS" if scores[name] >= 0.7 else "FAIL",
                str(evidence.get(f"{name}_evidence", "")),
                str(evidence.get(f"{name}_explanation", "")) or (f"Measured score {scores[name]:.2f}." if name not in missing else "Required evidence was not supplied."),
            )
            for name in QUALITY_DIMENSIONS_V2
        )
        issues: list[str] = []
        if missing:
            issues.append("missing_required_evidence:" + ",".join(missing))
            gate = QualityGate.BLOCKED
        elif scores["technical_validity"] < 0.8 or scores["requirement_compliance"] < 0.5 or scores["consistency"] < 0.7:
            gate = QualityGate.FAIL
        elif min(scores["visual_quality"], scores["design_maturity"], scores["content_quality"], scores["requirement_compliance"]) < 0.65:
            gate = QualityGate.NEEDS_IMPROVEMENT
        elif min(scores.values()) < 0.7:
            gate = QualityGate.PASS_WITH_NOTES
        else:
            gate = QualityGate.PASS

        if float(evidence.get("repetitive_layout_ratio", 0.0)) > 0.6:
            issues.append("layout_repetition_exceeds_limit")
            scores["design_maturity"] = min(scores["design_maturity"], 0.6)
            gate = QualityGate.NEEDS_IMPROVEMENT if gate is not QualityGate.FAIL else gate
        if evidence.get("mostly_text_boxes_and_arrows"):
            issues.append("presentation_is_primarily_text_boxes_and_arrows")
            scores["design_maturity"] = min(scores["design_maturity"], 0.58)
            gate = QualityGate.NEEDS_IMPROVEMENT if gate not in {QualityGate.FAIL, QualityGate.BLOCKED} else gate
        if int(evidence.get("thematic_visuals", 0)) < int(evidence.get("minimum_thematic_visuals", 0)):
            issues.append("insufficient_relevant_visual_material")
            scores["media_relevance"] = min(scores["media_relevance"], 0.6)
            gate = QualityGate.NEEDS_IMPROVEMENT if gate not in {QualityGate.FAIL, QualityGate.BLOCKED} else gate
        if evidence.get("overflow") or evidence.get("clipping"):
            issues.append("render_overflow_or_clipping")
            scores["technical_validity"] = min(scores["technical_validity"], 0.6)
            gate = QualityGate.FAIL

        # Active self-critique: report up to three genuinely improvable dimensions.
        weakest = tuple(
            name for name, score in sorted(scores.items(), key=lambda item: (item[1], item[0]))
            if score < 0.95
        )[:3]
        gate, repairs = self.consistency.validate(gate, subchecks)
        return QualityReviewV2(artifact, gate, scores, subchecks, tuple(issues), weakest, repairs)

    @staticmethod
    def calibration_fixtures() -> dict[str, dict[str, float]]:
        return {
            "poor": {name: (0.9 if name == "technical_validity" else 0.35) for name in QUALITY_DIMENSIONS_V2},
            # Required checks remain above the hard-failure threshold while the
            # presentation/content dimensions intentionally require another pass.
            "acceptable": {
                name: (0.95 if name == "technical_validity" else 0.72 if name in {"requirement_compliance", "consistency"} else 0.62)
                for name in QUALITY_DIMENSIONS_V2
            },
            "good": {name: (1.0 if name == "technical_validity" else 0.78) for name in QUALITY_DIMENSIONS_V2},
            "excellent": {name: (1.0 if name == "technical_validity" else 0.92) for name in QUALITY_DIMENSIONS_V2},
        }


@dataclass(frozen=True, slots=True)
class VisualDesignPlan:
    content_structure: tuple[str, ...]
    communication_goal: str
    visual_strategy: tuple[str, ...]
    layout_sequence: tuple[str, ...]
    vocabulary: tuple[str, ...]
    avoid: tuple[str, ...]

    def public(self) -> dict[str, Any]: return asdict(self)


class VisualDesignPlanner:
    VOCABULARY = ("photo", "illustration", "diagram", "icon", "chart", "timeline", "process", "comparison", "matrix", "screenshot", "callout", "annotation")

    def plan(self, content: Iterable[str], goal: str, *, signals: Iterable[str] = ()) -> VisualDesignPlan:
        structure = tuple(str(item).strip() for item in content if str(item).strip())
        if not structure:
            raise ValueError("visual_plan_requires_content")
        value = " ".join((goal, *structure, *signals)).casefold()
        vocabulary: list[str] = []
        strategy: list[str] = []
        for words, kind in (
            (("fase", "stage", "historia", "evolución", "evolution"), "timeline"),
            (("flujo", "flow", "proceso", "process"), "process"),
            (("compar", "versus", "antes", "después"), "comparison"),
            (("dato", "gasto", "trend", "métrica"), "chart"),
            (("pantalla", "interfaz", "evidencia"), "screenshot"),
            (("embri", "anatom", "educativ"), "illustration"),
        ):
            if any(word in value for word in words): vocabulary.append(kind)
        if not vocabulary: vocabulary.append("diagram")
        strategy.extend(("content_first", "clear_focal_point", "controlled_variety", "meaningful_negative_space"))
        layouts = tuple("hero" if index == 0 else "visual_sequence" if "timeline" in vocabulary else "editorial" for index, _ in enumerate(structure))
        return VisualDesignPlan(structure, goal.strip(), tuple(strategy), layouts, tuple(dict.fromkeys(vocabulary)), ("card_grid_default", "generic_icon_spam", "decorative_gradient_boxes"))


class CompositionEngine:
    def review(self, *, balance: float, negative_space: float, alignment: float, visual_weight: float, focal_point: float, reading_path: float, repeated_silhouettes: int, page_count: int) -> dict[str, Any]:
        scores = {"balance": balance, "negative_space": negative_space, "alignment": alignment, "visual_weight": visual_weight, "focal_point": focal_point, "reading_path": reading_path}
        average = sum(max(0.0, min(1.0, value)) for value in scores.values()) / len(scores)
        repetition = repeated_silhouettes / max(1, page_count)
        return {"scores": scores, "average": round(average, 3), "repetition_ratio": round(repetition, 3), "passed": average >= 0.7 and repetition <= 0.6}


class VisualStorytellingEngine:
    def sequence(self, subject: str, beats: Iterable[str]) -> dict[str, Any]:
        items = tuple(str(item).strip() for item in beats if str(item).strip())
        if len(items) < 3:
            raise ValueError("visual_story_requires_three_beats")
        return {"subject": subject.strip(), "opening": items[0], "development": items[1:-1], "resolution": items[-1], "reading_path": "guided_sequence", "short_visible_copy": True}
