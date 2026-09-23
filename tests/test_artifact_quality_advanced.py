from __future__ import annotations

from archeon.artifacts import (
    ArtifactQualityEngineV2, CompositionEngine, QualityConsistencyValidator,
    QualityGate, VisualDesignPlanner, VisualStorytellingEngine,
)
from archeon.artifacts.quality_advanced import QUALITY_DIMENSIONS_V2, QualitySubcheck


def evidence(score: float = 0.8) -> dict[str, float]:
    return {name: score for name in QUALITY_DIMENSIONS_V2}


def test_technically_valid_but_ugly_is_not_a_pass() -> None:
    values = evidence(0.76)
    values.update({"technical_validity": 1.0, "visual_quality": 0.48, "design_maturity": 0.41})
    report = ArtifactQualityEngineV2().review("valid-but-ugly.pptx", values)
    assert report.gate is QualityGate.NEEDS_IMPROVEMENT
    assert not report.passed
    assert report.scores["technical_validity"] == 1.0
    assert {"design_maturity", "visual_quality"}.issubset(report.weakest_aspects)


def test_no_overflow_never_assigns_a_perfect_visual_score() -> None:
    values = evidence(0.68); values["technical_validity"] = 1.0; values["overflow"] = False
    report = ArtifactQualityEngineV2().review("plain.pptx", values)
    assert report.scores["visual_quality"] == 0.68
    assert report.scores["design_maturity"] == 0.68


def test_missing_evidence_is_blocked_instead_of_assumed_average() -> None:
    report = ArtifactQualityEngineV2().review("unknown.pdf", {"technical_validity": True})
    assert report.gate is QualityGate.BLOCKED
    assert any(issue.startswith("missing_required_evidence") for issue in report.issues)


def test_text_boxes_and_arrows_force_needs_improvement() -> None:
    values = evidence(0.82); values["technical_validity"] = 1.0
    values["mostly_text_boxes_and_arrows"] = True
    report = ArtifactQualityEngineV2().review("automatic-looking.pptx", values)
    assert report.gate is QualityGate.NEEDS_IMPROVEMENT
    assert report.scores["design_maturity"] == 0.58


def test_consistency_validator_downgrades_contradictory_overall_pass() -> None:
    gate, repairs = QualityConsistencyValidator().validate(QualityGate.PASS, (
        QualitySubcheck("technical_validity", "PASS", "reopened"),
        QualitySubcheck("media_relevance", "FAIL", "one generic icon", "Measured evidence is below threshold."),
    ))
    assert gate is QualityGate.NEEDS_IMPROVEMENT
    assert "overall_downgraded_due_to_failed_subcheck" in repairs


def test_unexplained_failed_subcheck_is_a_failure() -> None:
    gate, repairs = QualityConsistencyValidator().validate(QualityGate.PASS, (
        QualitySubcheck("content_quality", "FAIL"),
    ))
    assert gate is QualityGate.FAIL
    assert "failed_subcheck_requires_explanation" in repairs


def test_calibration_fixtures_rank_poor_to_excellent() -> None:
    engine = ArtifactQualityEngineV2(); fixtures = engine.calibration_fixtures()
    reports = {name: engine.review(name, value) for name, value in fixtures.items()}
    assert reports["poor"].gate is QualityGate.FAIL
    assert reports["acceptable"].gate is QualityGate.NEEDS_IMPROVEMENT
    assert reports["good"].gate is QualityGate.PASS
    assert reports["excellent"].gate is QualityGate.PASS


def test_visual_planner_starts_from_content_and_avoids_card_defaults() -> None:
    plan = VisualDesignPlanner().plan(
        ("Threat landscape", "Authentication flow", "Unsafe vs safe input", "Monitoring"),
        "Teach web security through a visual process and comparison",
    )
    assert plan.content_structure[0] == "Threat landscape"
    assert {"process", "comparison"}.issubset(plan.vocabulary)
    assert "card_grid_default" in plan.avoid


def test_composition_and_storytelling_require_real_structure() -> None:
    review = CompositionEngine().review(
        balance=.8, negative_space=.76, alignment=.85, visual_weight=.79,
        focal_point=.88, reading_path=.83, repeated_silhouettes=2, page_count=7,
    )
    assert review["passed"] and review["repetition_ratio"] < .3
    story = VisualStorytellingEngine().sequence("Embryology", ("Fertilization", "Development", "Prenatal relevance"))
    assert story["opening"] == "Fertilization" and story["resolution"] == "Prenatal relevance"
