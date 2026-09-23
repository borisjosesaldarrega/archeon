"""Writing preference parsing, separate from document layout and formatting."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class WritingStyle(StrEnum):
    NATURAL = "natural"
    STUDENT = "student"
    ACADEMIC = "academic"
    PROFESSIONAL = "professional"
    TECHNICAL = "technical"
    DIRECT = "direct"
    INFORMAL = "informal"
    EXECUTIVE = "executive"
    CREATIVE = "creative"
    CUSTOM = "custom"


class QualityProfile(StrEnum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    THOROUGH = "THOROUGH"


@dataclass(frozen=True, slots=True)
class WritingStyleProfile:
    style: WritingStyle = WritingStyle.NATURAL
    quality: QualityProfile = QualityProfile.BALANCED
    concise: bool = False
    avoid_generic_conclusion: bool = False
    natural_phrasing: bool = True
    formality: str = "appropriate"
    detail: str = "balanced"
    custom_instruction: str = ""

    def public(self) -> dict[str, Any]:
        value = asdict(self); value["style"] = self.style.value; value["quality"] = self.quality.value
        return value


class WritingStyleEngine:
    def resolve(self, text: str, *, document_kind: str = "", learned: dict[str, Any] | None = None) -> WritingStyleProfile:
        value = " ".join(text.casefold().split())
        style = WritingStyle.NATURAL
        patterns = (
            (WritingStyle.STUDENT, r"\b(?:estudiante|estudiantil|deber|actividad de clase)\b"),
            (WritingStyle.ACADEMIC, r"\b(?:acad[eé]mico|tesis|investigaci[oó]n)\b"),
            (WritingStyle.TECHNICAL, r"\b(?:t[eé]cnico|especificaci[oó]n|diagn[oó]stico)\b"),
            (WritingStyle.EXECUTIVE, r"\b(?:ejecutivo|directivos|direcci[oó]n)\b"),
            (WritingStyle.PROFESSIONAL, r"\b(?:profesional|informe|correo)\b"),
            (WritingStyle.CREATIVE, r"\b(?:creativo|original|imaginativo)\b"),
            (WritingStyle.INFORMAL, r"\b(?:informal|casual)\b"),
            (WritingStyle.DIRECT, r"\b(?:directo|al grano)\b"),
        )
        for candidate, pattern in patterns:
            if re.search(pattern, value): style = candidate; break
        if re.search(r"\b(?:no tan ia|m[aá]s humano|natural)\b", value) and style is WritingStyle.NATURAL:
            style = WritingStyle.NATURAL
        concise = bool(re.search(r"\b(?:m[aá]s corto|no tan largo|sin tanta cosa|no me pongas tanta cosa)\b", value))
        no_conclusion = bool(re.search(r"\b(?:sin conclusi[oó]n|no pongas conclusi[oó]n)\b", value))
        quality = QualityProfile.THOROUGH if re.search(r"\b(?:rev[ií]salo bien|aseg[uú]rate|perfecto|a fondo)\b", value) else QualityProfile.BALANCED
        if learned:
            concise = concise or bool(learned.get("concise"))
            no_conclusion = no_conclusion or bool(learned.get("avoid_generic_conclusion"))
        if document_kind.casefold() in {"thesis", "tesis"}: style = WritingStyle.ACADEMIC
        elif document_kind.casefold() in {"email", "correo"}: style = WritingStyle.PROFESSIONAL
        return WritingStyleProfile(
            style=style, quality=quality, concise=concise,
            avoid_generic_conclusion=no_conclusion,
            natural_phrasing=True,
            formality="low" if style in {WritingStyle.STUDENT, WritingStyle.INFORMAL} else "appropriate",
            detail="concise" if concise else "balanced",
            custom_instruction=text if style is WritingStyle.CUSTOM else "",
        )

    @staticmethod
    def prompt(profile: WritingStyleProfile) -> str:
        instructions = [
            f"Estilo: {profile.style.value}.",
            "Usa vocabulario apropiado al contexto, frases naturales y respuestas directas.",
            "Evita formalidad innecesaria, relleno genérico y estructuras repetitivas.",
            "No introduzcas errores intencionales ni hagas afirmaciones sin evidencia.",
        ]
        if profile.concise: instructions.append("Sé breve sin omitir requisitos.")
        if profile.avoid_generic_conclusion: instructions.append("No añadas una conclusión genérica.")
        return " ".join(instructions)
