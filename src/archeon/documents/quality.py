"""Final-artifact requirement, semantic and visual QA without self-scoring claims."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class RequirementResult:
    requirement: str
    status: str
    evidence: str
    location: str

    def public(self) -> dict[str, str]: return asdict(self)


class RequirementChecker:
    """Always evaluates reopened final files, never generation counters."""

    def check_docx(
        self, path: str | Path, requirements: list[dict[str, Any]],
    ) -> list[RequirementResult]:
        from docx import Document

        source = Path(path).expanduser().resolve()
        document = Document(source)
        paragraphs = [item.text.strip() for item in document.paragraphs]
        tables = [[[cell.text.strip() for cell in row.cells] for row in table.rows] for table in document.tables]
        text = "\n".join(paragraphs + [" | ".join(row) for table in tables for row in table])
        relationships = {relationship.target_ref for relationship in document.part.rels.values()}
        results: list[RequirementResult] = []
        for requirement in requirements:
            label = str(requirement["requirement"])
            pattern = requirement.get("pattern")
            minimum = int(requirement.get("minimum", 1))
            if pattern:
                matches = list(re.finditer(str(pattern), text, flags=re.I | re.M))
                ok = len(matches) >= minimum; evidence = f"{len(matches)} coincidencia(s) en el archivo final"
                location = self._location(paragraphs, str(pattern))
            elif requirement.get("image"):
                filename = Path(str(requirement["image"])).name
                ok = any(filename in value for value in relationships) or len(document.inline_shapes) >= minimum
                evidence = f"{len(document.inline_shapes)} imagen(es) insertada(s) en el archivo final"
                location = "figuras"
            elif requirement.get("table_rows") is not None:
                required_rows = int(requirement["table_rows"])
                actual = max((len(table) - 1 for table in tables), default=0)
                ok = actual >= required_rows; evidence = f"{actual} fila(s) de datos en la tabla final"; location = "tabla"
            else:
                ok = False; evidence = "regla no evaluable"; location = "no localizado"
            results.append(RequirementResult(label, "PASS" if ok else "FAIL", evidence, location))
        return results

    @staticmethod
    def _location(paragraphs: list[str], pattern: str) -> str:
        for index, paragraph in enumerate(paragraphs, 1):
            if re.search(pattern, paragraph, re.I): return f"párrafo {index}"
        return "contenido/tablas"

    def semantic_qa(self, path: str | Path, *, required_headings: tuple[str, ...] = ()) -> dict[str, Any]:
        from docx import Document

        document = Document(Path(path).expanduser().resolve())
        paragraphs = [item.text.strip() for item in document.paragraphs if item.text.strip()]
        joined = "\n".join(paragraphs)
        missing = [heading for heading in required_headings if heading.casefold() not in joined.casefold()]
        normalized = [re.sub(r"\s+", " ", item).casefold() for item in paragraphs if len(item) > 40]
        duplicates = sorted({item for item in normalized if normalized.count(item) > 1})
        filler = [phrase for phrase in ("En el mundo actual", "Es importante destacar que", "En conclusión") if phrase.casefold() in joined.casefold()]
        return {"missing_requirements": missing, "duplicated_paragraphs": len(duplicates), "generic_filler": filler, "passed": not missing and not duplicates and not filler}

    def visual_qa(self, rendered_pages: list[str | Path]) -> dict[str, Any]:
        from PIL import Image, ImageStat

        issues: list[dict[str, Any]] = []
        for index, value in enumerate(rendered_pages, 1):
            path = Path(value); image = Image.open(path).convert("RGB")
            if image.width < 800 or image.height < 1000: issues.append({"page": index, "issue": "low_render_resolution"})
            grayscale = image.convert("L"); stat = ImageStat.Stat(grayscale)
            if stat.mean[0] > 252 and stat.stddev[0] < 4: issues.append({"page": index, "issue": "blank_or_nearly_blank_page"})
        return {"pages_checked": len(rendered_pages), "issues": issues, "passed": bool(rendered_pages) and not issues}

    def check_xlsx(self, path: str | Path, *, required_sheets: tuple[str, ...], minimum_charts: int = 0) -> dict[str, Any]:
        from openpyxl import load_workbook
        source = Path(path).expanduser().resolve(); workbook = load_workbook(source, data_only=False)
        try:
            formulas = [str(cell.value) for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith("=")]
            error_cells = [f"{sheet.title}!{cell.coordinate}" for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str) and re.search(r"#(?:REF!|DIV/0!|VALUE!|NAME\?|N/A)", cell.value)]
            charts = sum(len(sheet._charts) for sheet in workbook.worksheets)
            tables = sum(len(sheet.tables) for sheet in workbook.worksheets)
            missing = [name for name in required_sheets if name not in workbook.sheetnames]
            return {"sheets": workbook.sheetnames, "missing_sheets": missing, "formula_count": len(formulas), "formula_errors": error_cells, "charts": charts, "tables": tables, "passed": not missing and bool(formulas) and not error_cells and charts >= minimum_charts}
        finally: workbook.close()

    def check_pptx(self, path: str | Path, *, expected_slides: int, rendered_slides: list[str | Path] = ()) -> dict[str, Any]:
        from pptx import Presentation
        presentation = Presentation(Path(path).expanduser().resolve()); titles: list[str] = []; tiny: list[dict[str, Any]] = []
        for slide_index, slide in enumerate(presentation.slides, 1):
            # Artifact-tool decks use fully editable native text boxes rather than
            # PowerPoint placeholders. Infer the visual title from the largest run
            # when a formal title placeholder is intentionally absent.
            inferred_title = ""; largest_points = -1.0
            if slide.shapes.title and slide.shapes.title.text.strip():
                inferred_title = slide.shapes.title.text.strip()
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False): continue
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.text.strip() and run.font.size:
                            points = run.font.size.pt
                            if points > largest_points:
                                largest_points = points; inferred_title = run.text.strip()
                            if points < 9: tiny.append({"slide": slide_index, "text": run.text[:40], "points": points})
            titles.append(inferred_title)
        visual = self._slide_visual_qa(list(rendered_slides)) if rendered_slides else {"pages_checked": 0, "issues": [], "passed": True}
        missing_titles = [index + 1 for index, title in enumerate(titles) if not title]
        return {"slides": len(presentation.slides), "titles": titles, "missing_titles": missing_titles, "tiny_text": tiny, "visual": visual, "passed": len(presentation.slides) == expected_slides and not missing_titles and not tiny and visual["passed"]}

    @staticmethod
    def _slide_visual_qa(rendered_slides: list[str | Path]) -> dict[str, Any]:
        from PIL import Image, ImageStat
        issues: list[dict[str, Any]] = []
        for index, value in enumerate(rendered_slides, 1):
            image = Image.open(Path(value)).convert("RGB")
            if image.width < 900 or image.height < 500: issues.append({"slide": index, "issue": "low_render_resolution"})
            stat = ImageStat.Stat(image.convert("L"))
            if stat.mean[0] > 252 and stat.stddev[0] < 4: issues.append({"slide": index, "issue": "blank_or_nearly_blank_slide"})
        return {"pages_checked": len(rendered_slides), "issues": issues, "passed": bool(rendered_slides) and not issues}

    def check_infographic(self, path: str | Path, *, required_phases: tuple[str, ...], rendered_slides: list[str | Path] = ()) -> dict[str, Any]:
        from pptx import Presentation
        presentation = Presentation(Path(path).expanduser().resolve())
        text = "\n".join(shape.text for slide in presentation.slides for shape in slide.shapes if getattr(shape, "has_text_frame", False))
        folded = text.casefold(); missing = [phase for phase in required_phases if phase.casefold() not in folded]
        # Match phase-heading lines before falling back to prose occurrences.
        # This avoids treating a description such as "the blastocyst implants"
        # as the location of the earlier Blastocyst stage.
        lines = [line.strip().casefold() for line in text.splitlines()]
        order = [lines.index(phase.casefold()) if phase.casefold() in lines else len(lines) + folded.find(phase.casefold()) for phase in required_phases]
        ordered = all(value >= 0 for value in order) and order == sorted(order)
        sources = "fuentes" in folded and any(marker in folded for marker in ("http", "ncbi.nlm.nih.gov", "medlineplus.gov"))
        nursing = "importancia para enfermería" in folded or "importancia para enfermeria" in folded
        visual = self.visual_qa(list(rendered_slides)) if rendered_slides else {"pages_checked": 0, "issues": [], "passed": True}
        return {"slides": len(presentation.slides), "missing_phases": missing, "timeline_order": ordered, "sources_visible": sources, "nursing_relevance": nursing, "visual": visual, "passed": len(presentation.slides) == 1 and not missing and ordered and sources and nursing and visual["passed"]}

    def check_web_project(self, root: str | Path) -> dict[str, Any]:
        source = Path(root).expanduser().resolve(); required = ("index.html", "styles.css", "app.js", "README.md")
        missing = [name for name in required if not (source / name).is_file()]
        html = (source / "index.html").read_text(encoding="utf-8") if not missing else ""
        css = (source / "styles.css").read_text(encoding="utf-8") if not missing else ""
        js = (source / "app.js").read_text(encoding="utf-8") if not missing else ""
        broken = [value for value in re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", html) if not value.startswith(("http", "#")) and not (source / value).is_file()]
        requirements = {"semantic_main": "<main" in html, "labels": "<label" in html or "aria-label" in html, "local_storage": "localStorage" in js, "responsive": "@media" in css, "filters": all(value in js for value in ("all", "pending", "completed"))}
        return {"missing_files": missing, "broken_resources": broken, "requirements": requirements, "passed": not missing and not broken and all(requirements.values())}

    def check_archive(self, path: str | Path, *, expected_files: tuple[str, ...]) -> dict[str, Any]:
        from archeon.artifacts import ArchiveEngineProvider
        provider = ArchiveEngineProvider(); verified = provider.verify(path)
        names = {str(item["path"]) for item in verified["members"]}
        missing = [name for name in expected_files if name not in names]
        return {"valid": verified["valid"], "missing_files": missing, "safe_to_extract": verified["safe_to_extract"], "warnings": verified["warnings"], "member_count": verified["member_count"], "sha256": verified["sha256"], "passed": verified["valid"] and verified["safe_to_extract"] and not missing}
