from __future__ import annotations

import json
import zipfile
from pathlib import Path

from archeon.artifacts import (
    ArtifactPreviewSurface, ArtifactProfile, ArtifactQualityEngine,
    AssignmentIntelligence, DesignIntentEngine, DiagramEngine,
    InfographicEngine, PrintLayoutEngine, VisualAsset, VisualAssetRouter,
    WebDesignEngine,
)
from archeon.artifacts.archive_intelligence import ArchiveEngineProvider


def test_human_feedback_becomes_concrete_design_actions() -> None:
    engine = DesignIntentEngine()
    ugly = engine.interpret("esa presentacion esta fea ponle cosas del tema no puro cuadrito", profile=ArtifactProfile.VISUAL_PRESENTATION)
    assert "add_thematic_visuals" in ugly.objectives
    assert "repetitive_cards" in ugly.avoid
    infographic = engine.interpret("la infografia parece puro texto pon imagenes que tengan que ver", profile=ArtifactProfile.INFOGRAPHIC)
    assert {"add_thematic_visuals", "reduce_visible_text"}.issubset(infographic.objectives)
    spreadsheet = engine.interpret("ese exel cuando lo paso a pdf se parte arreglalo", profile=ArtifactProfile.SPREADSHEET)
    assert "repair_print_layout" in spreadsheet.objectives
    student = engine.interpret("hazme el deber pero no quiero que parezca super profesional es una tarea normal")
    assert student.tone == "simple_student"


def test_quality_engine_reports_mediocre_but_valid_artifact() -> None:
    report = ArtifactQualityEngine().review("valid-but-weak.pptx", {
        "technical_validity": True, "instruction_compliance": True,
        "visual_design": 0.76, "media_relevance": 0.42,
        "thematic_visuals": 1, "minimum_thematic_visuals": 5,
        "repetitive_layout_ratio": 0.8,
    })
    assert report.scores["technical_validity"] == 1.0
    assert report.scores["media_relevance"] == 0.42
    assert {issue.code for issue in report.issues} >= {"weak_media_relevance", "insufficient_thematic_visuals", "template_repetition"}


def test_visual_router_distinguishes_evidence_and_illustration() -> None:
    router = VisualAssetRouter()
    assert router.choose("embryology scientific stages") == "generated_educational_illustration"
    assert router.choose("screen proof", evidence=True) == "real_screenshot_or_source_evidence"
    assert router.choose("team portrait", requires_real_photo=True) == "licensed_external_photo"
    assert router.relevant(VisualAsset("stages.png", "illustration", "explain developmental sequence", False, "generated", "original_generated"))
    assert not router.relevant(VisualAsset("dot.svg", "icon", "decorate", False, "generated", "original_generated"))


def test_diagram_infographic_web_and_print_plans_are_content_driven() -> None:
    diagram = DiagramEngine().plan("process", "Authentication flow", ("User", "Password", "MFA", "Session"))
    assert diagram.connectors == ((0, 1), (1, 2), (2, 3))
    info = InfographicEngine().plan("Embryology", ("Zygote", "Morula", "Fetus"))
    assert info["minimum_thematic_visuals"] == 3
    web = WebDesignEngine().plan("Manage tasks", ("create", "edit", "filter"))
    assert {"keyboard", "visible_focus", "reduced_motion"}.issubset(web["accessibility"])
    print_plan = PrintLayoutEngine().plan(used_columns=8, used_rows=20, print_area="A1:L20", header_row=3, chart_beside_summary=True)
    assert print_plan.orientation == "landscape" and print_plan.fit_to_width == 1 and print_plan.fit_to_height == 1
    assert PrintLayoutEngine.review_pdf(pages=1, columns_cut=False, orphan_chart=False, blank_pages=0, tiny_scale=False)["passed"]


def test_assignment_plan_preserves_multi_artifact_goal_and_missing_name() -> None:
    plan = AssignmentIntelligence().plan("Pon mi nombre, hazlo en Word y PDF con capturas y fuentes; sección Resultados")
    assert plan.formats == ("docx", "pdf")
    assert plan.visual_requirements == ("screenshots",)
    assert plan.sources_required and "authorized_user_name" in plan.missing_required_info


def test_preview_surface_is_scoped_and_never_executes_unknown_content(tmp_path: Path) -> None:
    root = tmp_path / "project"; root.mkdir(); inside = root / "index.html"; inside.write_text("<main>ok</main>")
    outside = tmp_path / "outside.html"; outside.write_text("no")
    surface = ArtifactPreviewSurface(); policy = surface.policy()
    assert surface.may_preview(root, inside)
    assert not surface.may_preview(root, outside)
    assert not policy.filesystem_access and not policy.external_navigation and not policy.execute_unknown_javascript


def test_archive_project_understanding_is_static(tmp_path: Path) -> None:
    source = tmp_path / "project.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("package.json", json.dumps({"dependencies": {"react": "1", "vite": "1"}}))
        archive.writestr("src/main.jsx", "export default function App() {}")
        archive.writestr("public/index.html", "<main></main>")
    result = ArchiveEngineProvider().analyze_project(source)
    assert result["project_type"] == "web_project"
    assert {"React", "Vite", "Web"}.issubset(result["stack"])
    assert result["static_only"] and not result["executed"]
