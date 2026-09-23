"""Build and validate the M6 live-site academic activity from real evidence files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from archeon.documents import (  # noqa: E402
    DocumentStyleProfile, EvidenceCapture, RequirementChecker, write_evidence_manifest,
)
from docx import Document  # noqa: E402
from docx.enum.table import WD_ALIGN_VERTICAL  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Inches, Pt, RGBColor  # noqa: E402
from pypdf import PdfReader  # noqa: E402


TITLE = "Actividad: Evaluación práctica de usabilidad y optimización de una página web"
URL = "https://www.python.org/"
CAPTIONS = (
    "Figura 1. Vista inicial del sitio revisado.",
    "Figura 2. Contenido observado después del desplazamiento.",
    "Figura 3. Comportamiento del sitio en una vista estrecha.",
)
FINDINGS = (
    ("La navegación de escritorio agrupa accesos de red y secciones principales en niveles diferenciados.", "Fortaleza", "OBSERVED: Figura 1 y DOM de navegación.", "Mantener rótulos breves y la separación visual entre niveles."),
    ("La página presenta accesos directos a inicio, descarga, documentación y empleos.", "Fortaleza", "OBSERVED: Figuras 1 y 2.", "Conservar estos accesos cerca del contenido inicial."),
    ("Noticias y eventos aparecen en bloques separados, con fechas visibles y enlaces a más contenido.", "Fortaleza", "OBSERVED: Figura 2.", "Mantener fechas y títulos fáciles de recorrer."),
    ("La vista de 390×844 se adapta sin desbordamiento horizontal durante la prueba.", "Fortaleza", "MEASURED: viewport 390×844; overflow horizontal = no.", "Repetir la comprobación en otros anchos y con zoom de texto."),
    ("La navegación superior ocupa una parte considerable del primer viewport estrecho antes del contenido principal.", "Oportunidad", "OBSERVED: Figura 3.", "Evaluar un encabezado móvil más compacto sin ocultar accesos esenciales."),
    ("El esquema DOM del carrusel combina un H3 con varios H1 para mensajes alternativos.", "Oportunidad", "OBSERVED: inventario de encabezados del DOM.", "Revisar que el encabezado principal expuesto a tecnologías de asistencia sea único y estable."),
    ("Se observaron enlace de salto, regiones main/nav/footer, búsqueda etiquetada y texto alternativo en la imagen inventariada.", "Fortaleza", "OBSERVED: inspección DOM/Accessibility.", "Conservar estas señales y verificarlas en cambios futuros."),
)
RECOMMENDATIONS = (
    "Reducir la altura ocupada por la navegación en la vista estrecha, porque la captura muestra que desplaza el mensaje principal hacia abajo.",
    "Revisar la jerarquía de encabezados del carrusel para que el orden semántico sea claro aunque cambie la diapositiva visible.",
    "Probar la cabecera con zoom de texto y otros anchos cercanos al breakpoint; esta revisión solo midió 390×844.",
    "Mantener agrupados Noticias y Próximos eventos, pero comprobar que los títulos largos sigan siendo fáciles de recorrer en móvil.",
    "Ejecutar una medición separada con herramientas de rendimiento antes de decidir cambios de caché, imágenes o JavaScript; esas métricas no se obtuvieron aquí.",
)
PLAN = (
    ("Alta", "Revisar el encabezado móvil y reducir su ocupación vertical.", "Impacta el acceso inicial al contenido en el viewport estrecho observado."),
    ("Media", "Auditar el orden de encabezados del carrusel con lector de pantalla.", "El DOM observado mezcla niveles H3 y H1 en esa zona."),
    ("Media", "Probar zoom de texto y varios anchos alrededor del breakpoint.", "Amplía la evidencia responsive más allá de 390×844."),
    ("Baja", "Medir Lighthouse y métricas de carga en una sesión aparte.", "Evita optimizar rendimiento con datos no medidos."),
)


def _font(run, size: float, *, bold: bool = False, color: str = "000000", italic: bool = False) -> None:
    run.font.name = "Arial"; run.font.size = Pt(size); run.bold = bold; run.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Arial")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Arial")


def _shade(cell, fill: str) -> None:
    shading = OxmlElement("w:shd"); shading.set(qn("w:fill"), fill); cell._tc.get_or_add_tcPr().append(shading)


def _set_cell_margins(cell, top: int = 90, bottom: int = 90, start: int = 110, end: int = 110) -> None:
    properties = cell._tc.get_or_add_tcPr(); margins = properties.first_child_found_in("w:tcMar")
    if margins is None: margins = OxmlElement("w:tcMar"); properties.append(margins)
    for side, value in (("top", top), ("bottom", bottom), ("start", start), ("end", end)):
        node = margins.find(qn(f"w:{side}"))
        if node is None: node = OxmlElement(f"w:{side}"); margins.append(node)
        node.set(qn("w:w"), str(value)); node.set(qn("w:type"), "dxa")


def _table(document: Document, headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...], widths: tuple[int, ...], font_size: float = 8.5):
    table = document.add_table(rows=1, cols=len(headers)); table.style = "Table Grid"; table.autofit = False
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text; _shade(cell, "D9EAF7"); cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        for run in cell.paragraphs[0].runs: _font(run, font_size, bold=True, color="1F4E79")
    for values in rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, values):
            cell.text = text; cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0); paragraph.paragraph_format.line_spacing = 1.0
                for run in paragraph.runs: _font(run, font_size)
    properties = table._tbl.tblPr
    width_node = properties.find(qn("w:tblW"))
    if width_node is None: width_node = OxmlElement("w:tblW")
    width_node.set(qn("w:type"), "dxa"); width_node.set(qn("w:w"), str(sum(widths)))
    if width_node.getparent() is None: properties.append(width_node)
    indent = properties.find(qn("w:tblInd"))
    if indent is None: indent = OxmlElement("w:tblInd")
    indent.set(qn("w:type"), "dxa"); indent.set(qn("w:w"), "110")
    if indent.getparent() is None: properties.append(indent)
    grid = table._tbl.tblGrid
    for child in list(grid): grid.remove(child)
    for value in widths:
        column = OxmlElement("w:gridCol"); column.set(qn("w:w"), str(value)); grid.append(column)
    for row in table.rows:
        for cell, value in zip(row.cells, widths):
            tcw = cell._tc.get_or_add_tcPr().get_or_add_tcW(); tcw.type = "dxa"; tcw.w = value
            _set_cell_margins(cell)
    repeat = OxmlElement("w:tblHeader"); repeat.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    return table


def _figure(document: Document, image: Path, caption: str, *, width: float = 6.05) -> None:
    paragraph = document.add_paragraph(); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run().add_picture(str(image), width=Inches(width))
    cap = document.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(3); cap.paragraph_format.space_after = Pt(6)
    _font(cap.add_run(caption), 9, italic=True, color="555555")


def evidence(output_dir: Path) -> list[EvidenceCapture]:
    values = [
        ("evidence-01-home.png", "home", CAPTIONS[0], "1280x720"),
        ("evidence-02-scroll.png", "scroll", CAPTIONS[1], "1280x720; scrollY=650"),
        ("evidence-03-responsive.png", "responsive", CAPTIONS[2], "390x844"),
    ]
    captures = [EvidenceCapture.from_file(
        output_dir / filename, source="Codex In-app Browser", task_step=step,
        target="python.org homepage", caption=caption, url=URL, viewport=viewport,
    ) for filename, step, caption, viewport in values]
    write_evidence_manifest(output_dir / "EVIDENCE-MANIFEST.json", captures)
    return captures


def build(output_dir: Path) -> Path:
    captures = evidence(output_dir)
    path = output_dir / "Evaluacion_Web_Python_ARCHI.docx"
    path.unlink(missing_ok=True)
    document = Document()
    DocumentStyleProfile(cover=True, heading_color="1F4E79").apply_docx(document)
    styles = document.styles
    styles["Normal"].paragraph_format.line_spacing = 1.15
    styles["Normal"].paragraph_format.space_after = Pt(6)

    # Page 1 - simple cover and review facts.
    spacer = document.add_paragraph(); spacer.paragraph_format.space_after = Pt(72)
    title = document.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(18); _font(title.add_run(TITLE), 20, bold=True, color="1F4E79")
    site = document.add_paragraph(); site.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(site.add_run("Sitio evaluado: python.org"), 13, bold=True, color="365F91")
    document.add_page_break()

    # Page 2 - introduction, facts and desktop structure.
    document.add_heading("Introducción", 1)
    document.add_paragraph("En esta actividad revisé la página principal de python.org directamente en el navegador. Observé su estructura, la navegación, la forma de organizar el contenido y su comportamiento en una pantalla estrecha. Las recomendaciones se apoyan en lo visto durante la prueba; no se inventaron métricas de rendimiento.")
    document.add_heading("Datos de la revisión", 1)
    facts = (
        ("URL", URL), ("Fecha", datetime.now().astimezone().strftime("%d/%m/%Y")),
        ("Navegador", "Codex In-app Browser (Chromium controlado)"),
        ("Viewport de escritorio", "1280×720"), ("Viewport estrecho", "390×844"),
        ("Métricas de carga", "No medidas: no se ejecutó Lighthouse ni DevTools Performance"),
    )
    _table(document, ("Dato", "Valor"), facts, (2100, 6840), 9.5)
    document.add_heading("Estructura y navegación", 1)
    document.add_paragraph("OBSERVED: En escritorio, la cabecera separa los accesos de la red Python de las secciones principales. También ofrece búsqueda, donación y categorías como About, Downloads, Documentation, Community, News y Events. Debajo aparece un mensaje introductorio y accesos rápidos para comenzar, descargar Python, consultar documentación o revisar empleos.")
    _figure(document, Path(captures[0].image_path), CAPTIONS[0], width=5.7)
    document.add_page_break()

    # Page 3 - content, legibility and scrolled organization.
    document.add_heading("Contenido y legibilidad", 1)
    document.add_paragraph("OBSERVED: Los títulos de las secciones se diferencian por tamaño y cada bloque mantiene una función clara. El texto se presenta en fragmentos cortos y los enlaces importantes usan un color distinto. El contraste parece suficiente para leer en la captura, pero no se midió una relación numérica y por eso no se afirma cumplimiento de un estándar concreto.")
    document.add_paragraph("La cantidad de información es alta, aunque está dividida por temas. En lugar de mostrar un solo párrafo largo, la página separa aprendizaje, descargas, documentación, empleos, noticias, eventos, historias y usos de Python.")
    document.add_heading("Desplazamiento y organización", 1)
    document.add_paragraph("OBSERVED: Después de un desplazamiento real de 650 píxeles aparecieron los bloques Get Started, Download, Docs y Jobs, seguidos de Latest News y Upcoming Events. Las noticias y los eventos incluyen fechas, mientras que Success Stories y Use Python for… amplían el contenido sin mezclarse con esos listados.")
    _figure(document, Path(captures[1].image_path), CAPTIONS[1], width=5.75)

    # Page 4 - responsive and accessibility evidence.
    document.add_heading("Responsive", 1)
    document.add_paragraph("MEASURED: La vista se cambió a 390×844. El ancho del contenido fue de 375 píxeles y no se detectó desbordamiento horizontal. Los elementos se reorganizaron en una sola columna y el texto siguió dentro del viewport.")
    document.add_paragraph("OBSERVED: La navegación superior se apila verticalmente y conserva sus accesos, pero ocupa una parte grande de la pantalla antes del mensaje principal. Esto no demuestra un error funcional; sí señala una oportunidad para que el contenido principal aparezca antes en móvil.")
    _figure(document, Path(captures[2].image_path), CAPTIONS[2], width=2.35)
    document.add_heading("Accesibilidad observable", 1)
    document.add_paragraph("OBSERVED: El DOM expuso un enlace “Skip to content”, dos regiones de navegación, una región principal y un pie. El campo de búsqueda tenía la etiqueta “Search This Site” y la imagen inventariada tenía texto alternativo. También se observó que el carrusel combina un H3 con varios H1; conviene revisar ese orden con una prueba específica de lector de pantalla.")
    document.add_heading("Rendimiento observable", 1)
    document.add_paragraph("OBSERVED: La página mostró su navegación, contenido y listados durante la sesión sin un bloqueo visible. Esta observación solo describe la interacción realizada. No equivale a una medición de velocidad, estabilidad visual o peso de red.")
    document.add_page_break()

    # Page 5 - findings from the final evidence.
    document.add_heading("Tabla de hallazgos", 1)
    document.add_paragraph("Los tipos distinguen fortalezas de oportunidades. No se marcó un problema cuando la evidencia disponible no era suficiente.")
    _table(document, ("Hallazgo", "Tipo", "Evidencia", "Recomendación"), FINDINGS, (3150, 1200, 2200, 2390), 8.3)
    document.add_page_break()

    # Page 6 - recommendations and priority plan. No generic conclusion.
    document.add_heading("Oportunidades de optimización", 1)
    for recommendation in RECOMMENDATIONS:
        document.add_paragraph(recommendation, style="List Number")
    note = document.add_paragraph()
    _font(note.add_run("No medido: "), 10.5, bold=True, color="1F4E79")
    _font(note.add_run("Lighthouse, tiempo de carga, LCP, FCP, CLS, peso total y cantidad de solicitudes. Cualquier ajuste de rendimiento debe partir de una medición posterior."), 10.5)
    document.add_heading("Plan de mejora", 1)
    _table(document, ("Prioridad", "Acción", "Motivo"), PLAN, (1200, 3650, 4090), 8.5)

    document.core_properties.title = TITLE
    document.core_properties.subject = "Revisión práctica y verificable de python.org"
    document.core_properties.author = "ARCHI"
    document.save(path)
    return path


def validate(output_dir: Path, *, render_dir: Path | None = None) -> dict[str, object]:
    docx = output_dir / "Evaluacion_Web_Python_ARCHI.docx"
    pdf = output_dir / "Evaluacion_Web_Python_ARCHI.pdf"
    manifest_path = output_dir / "EVIDENCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence_items = list(manifest.get("evidence", []))
    document = Document(docx)
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    joined = "\n".join(paragraphs)
    findings_table = next((table for table in document.tables if table.rows and table.cell(0, 0).text.strip() == "Hallazgo"), None)
    findings_count = max(0, len(findings_table.rows) - 1) if findings_table is not None else 0
    opportunity_heading = next((index for index, value in enumerate(paragraphs) if value == "Oportunidades de optimización"), -1)
    plan_heading = next((index for index, value in enumerate(paragraphs) if value == "Plan de mejora"), -1)
    recommendations_count = max(0, plan_heading - opportunity_heading - 2) if opportunity_heading >= 0 and plan_heading > opportunity_heading else 0
    pdf_pages = 0; pdf_valid = False
    if pdf.is_file():
        reader = PdfReader(pdf); pdf_pages = len(reader.pages)
        pdf_valid = pdf_pages > 0 and all(bool((page.extract_text() or "").strip()) for page in reader.pages)
    rendered_pages = sorted(render_dir.glob("page-*.png")) if render_dir and render_dir.is_dir() else []
    checker = RequirementChecker()
    checks = checker.check_docx(docx, [
        {"requirement": "Portada exacta", "pattern": r"Actividad: Evaluación práctica.*página web"},
        {"requirement": "URL", "pattern": r"https://www\.python\.org/"},
        {"requirement": "Caption 1", "pattern": r"^Figura 1\. Vista inicial del sitio revisado\.$"},
        {"requirement": "Caption 2", "pattern": r"^Figura 2\. Contenido observado después del desplazamiento\.$"},
        {"requirement": "Caption 3", "pattern": r"^Figura 3\. Comportamiento del sitio en una vista estrecha\.$"},
        {"requirement": "Seis hallazgos", "table_rows": 6},
        {"requirement": "No medido", "pattern": r"No medido:"},
    ])
    semantic = checker.semantic_qa(docx, required_headings=(
        "Introducción", "Datos de la revisión", "Estructura y navegación", "Contenido y legibilidad",
        "Desplazamiento y organización", "Responsive", "Tabla de hallazgos",
        "Oportunidades de optimización", "Plan de mejora",
    ))
    visual = checker.visual_qa([str(path) for path in rendered_pages]) if rendered_pages else {"pages_checked": 0, "issues": [], "passed": False}
    failed = [item.requirement for item in checks if item.status != "PASS"]
    if not semantic["passed"]: failed.extend(semantic["missing_requirements"] or ["semantic_qa"])
    result = {
        "live_site_accessed": bool(evidence_items) and all(item.get("url") == URL for item in evidence_items),
        "screenshots_real": sum(Path(str(item.get("image_path", ""))).is_file() and bool(item.get("sha256")) for item in evidence_items),
        "desktop_view_recorded": any(item.get("viewport") == "1280x720" for item in evidence_items),
        "responsive_view_recorded": any(item.get("viewport") == "390x844" for item in evidence_items),
        "findings_count": findings_count,
        "recommendations_count": recommendations_count,
        "docx_valid": docx.is_file() and len(document.inline_shapes) == 3 and not failed,
        "pdf_valid": pdf_valid,
        "pdf_pages": pdf_pages,
        "visual_pages_checked": len(rendered_pages),
        "visual_qa": visual,
        "semantic_qa": semantic,
        "requirement_results": [item.public() for item in checks],
        "requirements_failed": failed,
    }
    (output_dir / "ARCHI-M6-ACTIVITY-VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--validate-only", action="store_true"); parser.add_argument("--render-dir", type=Path)
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.validate_only: build(args.output_dir)
    result = validate(args.output_dir, render_dir=args.render_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["docx_valid"] and (not args.validate_only or result["pdf_valid"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
