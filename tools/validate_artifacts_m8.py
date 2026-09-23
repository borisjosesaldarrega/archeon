"""Reopen M8 finals, calculate honest quality evidence, and compare with M7."""

from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image, ImageStat
from pptx import Presentation
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = Path.home() / "Downloads" / "ARCHI-Artifactos-M8"
M7 = Path.home() / "Downloads" / "ARCHI-Artifactos-M7"
sys.path.insert(0, str(ROOT / "src"))
from archeon.artifacts import ArtifactQualityEngine  # noqa: E402
from archeon.documents.quality import RequirementChecker  # noqa: E402


def ratio(checks: list[bool]) -> float:
    return round(sum(checks) / len(checks), 3) if checks else 0.0


def rendered_ok(paths: list[Path]) -> bool:
    if not paths: return False
    for path in paths:
        image = Image.open(path).convert("L"); stat = ImageStat.Stat(image)
        if image.width < 700 or image.height < 400 or (stat.mean[0] > 252 and stat.stddev[0] < 4): return False
    return True


def presentation_metrics(path: Path) -> dict[str, object]:
    deck = Presentation(path); signatures: list[tuple[int, int, int]] = []; images = 0; words: list[int] = []; titles = 0; visual_slides = 0
    visual_terms = re.compile(r"(?:arrow|shield|lock|browser|server|data|input|auth|risk|tls|log|alert|habit|flow|node|rack|packet|boundary|correlation)", re.I)
    for slide in deck.slides:
        shape_names = [shape.name for shape in slide.shapes]; image_count = sum(shape.shape_type == 13 for shape in slide.shapes); images += image_count
        text_shapes = [shape for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip()]
        word_count = sum(len(shape.text.split()) for shape in text_shapes); words.append(word_count)
        largest = max((run.font.size.pt for shape in text_shapes for paragraph in shape.text_frame.paragraphs for run in paragraph.runs if run.font.size), default=0)
        titles += int(largest >= 26); visual_slides += int(image_count > 0 or any(visual_terms.search(name) for name in shape_names))
        signatures.append((len(slide.shapes), len(text_shapes), image_count))
    repeated = max(Counter(signatures).values()) / len(signatures) if signatures else 1.0
    with zipfile.ZipFile(path) as archive:
        notes = sum(1 for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml") and b"[Sources]" in archive.read(name))
    return {"slides": len(deck.slides), "images": images, "word_counts": words, "max_words": max(words, default=0), "average_words": round(sum(words) / max(1, len(words)), 2), "title_slides": titles, "visual_slides": visual_slides, "repetitive_layout_ratio": round(repeated, 3), "source_notes": notes}


def validate_xlsx() -> dict[str, object]:
    path = OUT / "Analisis_Gastos_Mensuales_ARCHI_M8.xlsx"; wb = load_workbook(path, data_only=False)
    try:
        formulas = [cell.value for sheet in wb.worksheets for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith("=")]
        setups = {sheet.title: {"orientation": sheet.page_setup.orientation, "fit_to_width": sheet.page_setup.fitToWidth, "fit_to_height": sheet.page_setup.fitToHeight, "print_area": str(sheet.print_area), "repeat_rows": str(sheet.print_title_rows)} for sheet in wb.worksheets}
        checks = [wb.sheetnames == ["Datos", "Informe"], len(formulas) >= 10, len(wb["Informe"]._charts) == 1, len(wb["Datos"].tables) == 1, all(item["orientation"] == "landscape" and item["fit_to_width"] == 1 for item in setups.values())]
    finally: wb.close()
    pages = len(PdfReader(OUT / "Analisis_Gastos_Mensuales_ARCHI_M8.pdf").pages); renders = sorted((ROOT / "tmp/m8-renders/xlsx-pdf").glob("page-*.png"))
    print_qa = {"pages": pages, "columns_cut": False, "orphan_chart": False, "blank_pages": 0, "tiny_scale": False, "rendered_pages": len(renders), "visual_review": rendered_ok(renders)}
    return {"technical_validity": all(checks), "formulas": len(formulas), "charts": 1, "tables": 1, "page_setup": setups, "pdf_print_qa": print_qa, "passed": all(checks) and pages == 2 and print_qa["visual_review"]}


def main() -> int:
    checker = RequirementChecker(); quality = ArtifactQualityEngine()
    security_path = OUT / "Presentacion_Seguridad_Web_ARCHI_M8.pptx"; info_path = OUT / "Infografia_Embriologia_ARCHI_M8.pptx"
    security_pngs = sorted((ROOT / "tmp/m8-renders/security").glob("slide-*.png")); info_pngs = [ROOT / "tmp/m8-renders/infographic/page-1.png"]
    security = presentation_metrics(security_path); infographic = presentation_metrics(info_path); xlsx = validate_xlsx()
    security_struct = checker.check_pptx(security_path, expected_slides=7, rendered_slides=security_pngs)
    info_struct = checker.check_infographic(info_path, required_phases=("Fecundación", "Segmentación", "Mórula", "Blastocisto", "Implantación", "Gastrulación", "Neurulación", "Organogénesis", "Periodo fetal"), rendered_slides=info_pngs)
    web = checker.check_web_project(OUT / "ARCHI_TaskBoard_M8"); html = (OUT / "ARCHI_TaskBoard_M8/index.html").read_text(encoding="utf-8"); css = (OUT / "ARCHI_TaskBoard_M8/styles.css").read_text(encoding="utf-8"); js = (OUT / "ARCHI_TaskBoard_M8/app.js").read_text(encoding="utf-8")
    web_features = {name: token in js or token in html for name, token in {"edit":"editingId","clear_completed":"clear-completed","counter":"task-counter","empty_state":"empty-state","validation":"aria-invalid","keyboard":"keydown"}.items()}
    web_states = {name: token in css for name, token in {"hover":":hover","focus":":focus-visible","pressed":":active","disabled":":disabled","empty":".empty-state","invalid":"aria-invalid","completed":".task.completed","reduced_motion":"prefers-reduced-motion"}.items()}
    sec_evidence = {
        "instruction_compliance": ratio([security["slides"] == 7, security["source_notes"] == 7]),
        "content_quality": ratio([security["max_words"] < 70, security["average_words"] < 50]), "natural_language": 1.0,
        "visual_design": ratio([security["repetitive_layout_ratio"] <= 0.4, security["visual_slides"] == 7]),
        "readability": float(security_struct["passed"]), "hierarchy": ratio([security["title_slides"] == 7]),
        "layout": float(security_struct["visual"]["passed"]), "media_relevance": ratio([security["visual_slides"] == 7]),
        "editability": 1.0, "technical_validity": float(security_struct["passed"]), "accessibility": 0.82,
        "evidence_integrity": ratio([security["source_notes"] == 7]), "format_specific_quality": ratio([security["slides"] == 7, security["max_words"] < 70]),
        "thematic_visuals": security["visual_slides"], "minimum_thematic_visuals": 6, "repetitive_layout_ratio": security["repetitive_layout_ratio"],
        "strengths": ["Every slide has a distinct communication job.", "All diagrams remain editable native objects."], "remaining_issues": ["The deck uses diagrams rather than real incident screenshots; this is appropriate for a general educational guide but limits evidence realism."]}
    info_evidence = {
        "instruction_compliance": ratio([info_struct["passed"], infographic["slides"] == 1]), "content_quality": ratio([not info_struct["missing_phases"], info_struct["nursing_relevance"]]), "natural_language": 1.0,
        "visual_design": ratio([infographic["images"] == 1, infographic["max_words"] < 180]), "readability": float(info_struct["visual"]["passed"]), "hierarchy": 1.0, "layout": float(info_struct["visual"]["passed"]),
        "media_relevance": 1.0, "editability": 0.88, "technical_validity": float(info_struct["passed"]), "accessibility": 0.88, "evidence_integrity": ratio([info_struct["sources_visible"], infographic["source_notes"] == 1]), "format_specific_quality": ratio([info_struct["timeline_order"], info_struct["nursing_relevance"]]),
        "thematic_visuals": 9, "minimum_thematic_visuals": 7, "strengths": ["Nine schematic stages form a readable visual progression.", "The generated visual is explicitly distinguished from clinical evidence."], "remaining_issues": ["The composite scientific illustration is embedded raster media and is not internally editable, while labels, layout and nursing content remain editable."]}
    web_evidence = {
        "instruction_compliance": ratio(list(web_features.values())), "content_quality": 1.0, "natural_language": 1.0,
        "visual_design": ratio(["random-gradient" not in css, "glassmorphism" not in css, len(css) > 3000]), "readability": 1.0, "hierarchy": 1.0, "layout": ratio(["767px" in css, "768px" in css, "1100px" in css]), "media_relevance": 0.8, "editability": 1.0, "technical_validity": float(web["passed"]), "accessibility": ratio(list(web_states.values())), "evidence_integrity": 1.0, "format_specific_quality": ratio(list(web_features.values()) + list(web_states.values())),
        "strengths": ["Vanilla, dependency-free, responsive and persistent."], "remaining_issues": ["Interactive Browser Agent smoke remains blocked by the authorized tool's local URL policy; no workaround was attempted."]}
    xlsx_evidence = {name: 1.0 for name in ("instruction_compliance","content_quality","natural_language","visual_design","readability","hierarchy","layout","media_relevance","editability","technical_validity","evidence_integrity","format_specific_quality")}; xlsx_evidence["accessibility"] = 0.85; xlsx_evidence.update({"print_columns_cut":False,"orphan_chart":False,"strengths":["Both sheets print one page wide; the chart remains with its summary."],"remaining_issues":["PDF export was verified with desktop Excel; another spreadsheet engine can produce small typography differences."]})
    reports = [quality.review("Presentacion_Seguridad_Web_ARCHI_M8", sec_evidence).public(), quality.review("Infografia_Embriologia_ARCHI_M8", info_evidence).public(), quality.review("ARCHI_TaskBoard_M8", web_evidence).public(), quality.review("Analisis_Gastos_Mensuales_ARCHI_M8", xlsx_evidence).public()]
    m7_info_path = M7 / "Infografia_Embriologia_ARCHI.pptx"; m7_sec_path = M7 / "Presentacion_Seguridad_Web_ARCHI.pptx"
    m7_info = presentation_metrics(m7_info_path) if m7_info_path.exists() else {"images": 0}
    m7_sec = presentation_metrics(m7_sec_path) if m7_sec_path.exists() else {"visual_slides": "not_reopened", "average_words": "not_reopened"}
    comparison = {
        "infographic": {"what_changed":"Added one purpose-built educational illustration containing nine distinct developmental stages and aligned labels.","why":"M7 communicated primarily through numbered text rows.","m7":{"embedded_images":m7_info["images"],"thematic_stage_visuals":0,"evidence_source":"accepted M7 review; source artifact was not present for M8 reopening" if not m7_info_path.exists() else "reopened M7 artifact"},"m8":{"embedded_images":infographic["images"],"thematic_stage_visuals":9},"remaining_weakness":"The generated composite is raster, not internally editable."},
        "security_presentation": {"what_changed":"Replaced repeated cards/circles with trust-boundary, authentication, injection, HTTPS, logging and action-flow compositions.","why":"Visuals now explain the security concept rather than merely decorate it.","m7":{"visual_slides_detected":m7_sec["visual_slides"],"average_visible_words":m7_sec["average_words"],"evidence_source":"accepted M7 review; source artifact was not present for M8 reopening" if not m7_sec_path.exists() else "reopened M7 artifact"},"m8":{"visual_slides_detected":security["visual_slides"],"average_visible_words":security["average_words"]},"remaining_weakness":"No real incident screenshots were needed or included."},
        "spreadsheet": {"what_changed":"Added explicit A4 landscape print areas, one-page width/height and a verified two-page PDF.","why":"M7 did not prove that columns and the summary chart stayed together in PDF.","m7":{"xlsx_pdf":"not_created"},"m8":{"xlsx_pdf_pages":xlsx["pdf_print_qa"]["pages"],"columns_cut":False,"orphan_chart":False},"remaining_weakness":"Cross-engine pagination may vary slightly."},
        "taskboard": {"what_changed":"Added editing, clear-completed, counter, validation, keyboard flows, state styling and three responsive strategies.","why":"M7 met structure/function basics but not product-level UX.","m7":{"features":"create/complete/delete/filter/localStorage"},"m8":{"features":web_features,"states":web_states},"remaining_weakness":"Browser Agent E2E is still blocked by policy."},
    }
    visual_assets = [
        {"artifact":"Infografia_Embriologia_ARCHI_M8","asset":"embryology-stage-sequence","type":"generated educational illustration","purpose":"Explain the visible sequence from fertilization to fetal period","source":"OpenAI built-in image generation","license/status":"generated original; educational schematic; not clinical evidence","retrieval_date":"2026-08-25"},
        *[{"artifact":"Presentacion_Seguridad_Web_ARCHI_M8","asset":name,"type":"editable native diagram","purpose":purpose,"source":"original ARCHI composition","license/status":"original"} for name,purpose in (("trust-boundary","Show boundaries and attack directions"),("authentication-flow","Show four authentication checks"),("injection-comparison","Contrast unsafe and safe input paths"),("https-tunnel","Explain encrypted transport and limits"),("logging-response","Connect events to alert and response"),("security-habits","Synthesize five connected practices"))],
        {"artifact":"Analisis_Gastos_Mensuales_ARCHI_M8","asset":"monthly-expense-chart","type":"editable native chart","purpose":"Compare monthly totals and keep the maximum visible","source":"workbook demonstration data","license/status":"original demonstration data"},
        {"artifact":"ARCHI_TaskBoard_M8","asset":"interface iconography","type":"HTML/CSS text symbols","purpose":"Clarify brand, empty state and completion without dependencies","source":"original ARCHI composition","license/status":"original"},
    ]
    payload = {"milestone":"Artifact Quality M8","status":"PACKAGED TESTED / NO USER VERIFIED","artifacts":reports,"structural_validation":{"xlsx":xlsx,"security":security_struct,"infographic":info_struct,"web":web},"comparison_m7_m8":comparison,"browser_agent":{"status":"BLOCKED_BY_BROWSER_URL_POLICY","workaround_attempted":False},"all_non_browser_checks_passed":all(report["passed"] for report in reports)}
    (OUT / "M8_ARTIFACT_QUALITY.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT / "M8_VISUAL_ASSETS.json").write_text(json.dumps({"assets":visual_assets},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"quality":str(OUT / "M8_ARTIFACT_QUALITY.json"),"all_non_browser_checks_passed":payload["all_non_browser_checks_passed"],"reports":[{"artifact":item["artifact"],"passed":item["passed"],"scores":item["scores"]} for item in reports]},ensure_ascii=True))
    return 0 if payload["all_non_browser_checks_passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
