"""Create deterministic document fixtures with the bundled artifact runtime."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas


def main() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fixtures.mkdir(exist_ok=True)

    pdf = fixtures / "document.pdf"
    canvas = Canvas(str(pdf), pagesize=letter)
    canvas.setTitle("ARCHEON Document Fixture")
    canvas.drawString(72, 720, "ARCHI DOCUMENT TEST PAGE ONE")
    canvas.showPage()
    canvas.drawString(72, 720, "Invoice 2026-ARC-042 belongs to Boris Saldarrega.")
    canvas.save()

    docx = fixtures / "document.docx"
    document = Document()
    document.add_heading("ARCHEON Document Fixture", level=1)
    document.add_paragraph("Original document paragraph.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Field"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Invoice"
    table.cell(1, 1).text = "2026-ARC-042"
    document.save(docx)


if __name__ == "__main__":
    main()
