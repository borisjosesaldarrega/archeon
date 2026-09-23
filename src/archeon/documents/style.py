"""Real document property profiles parsed from natural language."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentStyleProfile:
    template: str = "Student Simple"
    page_size: str = "A4"
    orientation: str = "portrait"
    margin: str = "normal"
    font_family: str = "Arial"
    font_size: float = 11.0
    line_spacing: float = 1.15
    heading_color: str = "1F4E79"
    body_alignment: str = "left"
    page_numbers: bool = True
    header: bool = False
    footer: bool = True
    cover: bool = False
    columns: int = 1
    locale: str = "es"
    direction: str = "ltr"

    def public(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "DocumentStyleProfile":
        if not value: return cls()
        allowed = cls.__dataclass_fields__
        return cls(**{key: item for key, item in value.items() if key in allowed})

    @classmethod
    def for_locale(cls, locale: str) -> "DocumentStyleProfile":
        from archeon.core.language import locale_direction, normalize_locale

        code = normalize_locale(locale)
        fonts = {
            "zh": "Microsoft YaHei", "ja": "Yu Gothic", "ko": "Malgun Gothic",
            "ar": "Segoe UI", "hi": "Nirmala UI", "ru": "Arial",
        }
        return cls(font_family=fonts.get(code, "Arial"), locale=code, direction=locale_direction(code))

    @classmethod
    def interpret(cls, text: str, *, base: "DocumentStyleProfile | None" = None, locale: str = "es") -> "DocumentStyleProfile":
        current = asdict(base or cls.for_locale(locale))
        value = " ".join(text.casefold().split())
        current["orientation"] = "landscape" if re.search(r"\b(?:horizontal|apaisad[ao])\b", value) else current["orientation"]
        if re.search(r"\bmargen(?:es)? estrech", value): current["margin"] = "narrow"
        elif re.search(r"\bmargen(?:es)? normal", value): current["margin"] = "normal"
        font = re.search(r"\b(?:letra|fuente)\s+([a-z][a-z ]{1,24}?)(?:\s+(\d{1,2}(?:[.,]\d)?))?(?:\s|$)", value)
        if font:
            current["font_family"] = font.group(1).strip().title()
            if font.group(2): current["font_size"] = min(24.0, max(8.0, float(font.group(2).replace(",", "."))))
        spacing = re.search(r"interlineado\s+(1(?:[.,]\d{1,2})?|2)", value)
        if spacing: current["line_spacing"] = float(spacing.group(1).replace(",", "."))
        colors = {"morado": "7030A0", "azul": "1F4E79", "negro": "000000", "verde": "548235", "rojo": "C00000"}
        color = re.search(r"t[ií]tulos?\s+(?:en\s+)?(morado|azul|negro|verde|rojo)", value)
        if color: current["heading_color"] = colors[color.group(1)]
        if re.search(r"\b(?:pon|a[nñ]ade).*numeraci[oó]n", value): current["page_numbers"] = True
        if re.search(r"\bquita.*numeraci[oó]n", value): current["page_numbers"] = False
        if re.search(r"\bquita.*encabezado", value): current["header"] = False
        if re.search(r"\bportada\b", value): current["cover"] = not bool(re.search(r"\b(?:sin|quita)\s+(?:la\s+)?portada", value))
        columns = re.search(r"\b(uno|dos|tres|[1-3])\s+columnas?\b", value)
        if columns:
            token = columns.group(1)
            current["columns"] = {"uno": 1, "dos": 2, "tres": 3}[token] if token in {"uno", "dos", "tres"} else int(token)
        return cls(**current)

    def apply_docx(self, document: Any) -> None:
        """Apply explicit Word properties without importing python-docx until used."""
        from docx.enum.section import WD_ORIENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Mm, Pt, RGBColor

        margins = 12.7 if self.margin == "narrow" else 25.4
        for section in document.sections:
            if self.page_size.casefold() in {"letter", "carta"}:
                section.page_width, section.page_height = Mm(215.9), Mm(279.4)
            else:
                section.page_width, section.page_height = Mm(210), Mm(297)
            if self.orientation == "landscape":
                section.orientation = WD_ORIENT.LANDSCAPE
                section.page_width, section.page_height = section.page_height, section.page_width
            section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(margins)
            section.header_distance = Cm(1.25); section.footer_distance = Cm(1.25)
            if self.columns > 1:
                columns = section._sectPr.xpath("./w:cols")[0]
                columns.set(qn("w:num"), str(self.columns))
        normal = document.styles["Normal"]
        normal.font.name = self.font_family; normal.font.size = Pt(self.font_size)
        normal._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), self.font_family)
        normal._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), self.font_family)
        normal._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), self.font_family)
        normal._element.get_or_add_rPr().rFonts.set(qn("w:cs"), self.font_family)
        normal.paragraph_format.space_after = Pt(6); normal.paragraph_format.line_spacing = self.line_spacing
        normal.paragraph_format.alignment = {
            "center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(self.body_alignment, WD_ALIGN_PARAGRAPH.RIGHT if self.direction == "rtl" else WD_ALIGN_PARAGRAPH.LEFT)
        title = document.styles["Title"]
        title.font.name = self.font_family; title.font.size = Pt(24); title.font.bold = True
        title.font.color.rgb = RGBColor(0, 0, 0)
        title.paragraph_format.space_after = Pt(14)
        title.paragraph_format.keep_with_next = True
        title_rpr = title._element.get_or_add_rPr()
        title_rpr.rFonts.set(qn("w:ascii"), self.font_family)
        title_rpr.rFonts.set(qn("w:hAnsi"), self.font_family)
        title_rpr.rFonts.set(qn("w:eastAsia"), self.font_family)
        title_ppr = title._element.get_or_add_pPr()
        borders = title_ppr.find(qn("w:pBdr"))
        if borders is not None:
            title_ppr.remove(borders)
        if self.direction == "rtl":
            p_pr = normal._element.get_or_add_pPr()
            if p_pr.find(qn("w:bidi")) is None:
                p_pr.append(OxmlElement("w:bidi"))
        for name, size, before, after in (("Heading 1", 16, 14, 6), ("Heading 2", 13, 12, 5), ("Heading 3", 11.5, 8, 4)):
            style = document.styles[name]; style.font.name = self.font_family; style.font.size = Pt(size); style.font.bold = True
            style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), self.font_family)
            style._element.get_or_add_rPr().rFonts.set(qn("w:cs"), self.font_family)
            style.font.color.rgb = RGBColor.from_string(self.heading_color)
            style.paragraph_format.space_before = Pt(before); style.paragraph_format.space_after = Pt(after); style.paragraph_format.keep_with_next = True
            if self.direction == "rtl" and style._element.get_or_add_pPr().find(qn("w:bidi")) is None:
                style._element.get_or_add_pPr().append(OxmlElement("w:bidi"))
        if self.page_numbers:
            for section in document.sections:
                paragraph = section.footer.paragraphs[0]
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run()
                begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
                instruction = OxmlElement("w:instrText"); instruction.set(qn("xml:space"), "preserve"); instruction.text = " PAGE "
                end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
                run._r.extend((begin, instruction, end))
