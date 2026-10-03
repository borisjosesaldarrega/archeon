"""Semantic resolution for local date and time questions.

The resolver exposes declarative aliases and scoring signals so callers do not
grow a phrase-by-phrase chain for every way a person can ask the same thing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[^\W_]+", plain, re.UNICODE))


@dataclass(frozen=True, slots=True)
class TemporalField:
    field_id: str
    aliases: frozenset[str]


@dataclass(frozen=True, slots=True)
class TemporalResolution:
    fields: tuple[str, ...]
    confidence: float
    evidence: tuple[str, ...]
    concise: bool

    def answer(self, now: datetime) -> str:
        weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        values = {
            "day": f"{weekdays[now.weekday()]} {now.day}",
            "month": months[now.month - 1],
            "year": str(now.year),
            "time": f"{now:%H:%M}",
        }
        single_templates = {
            "day": "Hoy es {value}.",
            "month": "Estamos en {value}.",
            "year": "Estamos en {value}.",
            "time": "Son las {value}.",
        }
        combined_templates = {
            ("day", "month"): "Hoy es {day} de {month}.",
            ("month", "year"): "Estamos en {month} de {year}.",
            ("day", "month", "year"): "Hoy es {day} de {month} de {year}.",
        }
        if len(self.fields) == 1:
            field = self.fields[0]
            return single_templates[field].format(value=values[field])
        if template := combined_templates.get(self.fields):
            return template.format(**values)
        labels = {"day": "día", "month": "mes", "year": "año", "time": "hora"}
        facts = ", ".join(f"{labels[field]}: {values[field]}" for field in self.fields)
        return facts[:1].upper() + facts[1:] + "."

    def public(self) -> dict[str, object]:
        return {
            "intent": "local_date_time_query",
            "fields": list(self.fields),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "knowledge": "KNOWN",
        }


class TemporalQueryResolver:
    """Resolve temporal slots through registered aliases and weighted signals."""

    DEFAULT_FIELDS = (
        TemporalField("day", frozenset({"dia", "dia de hoy", "jornada", "day", "jour", "tag", "giorno", "今日", "今日の日付", "날짜", "день", "اليوم", "दिन"})),
        TemporalField("month", frozenset({"mes", "month", "mois", "monat", "mese", "月", "월", "месяц", "شهر", "महीना"})),
        TemporalField("year", frozenset({"ano", "year", "annee", "jahr", "anno", "年", "년", "год", "سنة", "साल"})),
        TemporalField("time", frozenset({"hora", "horas", "time", "heure", "uhrzeit", "ora", "几点", "现在几点", "시간", "몇 시", "время", "который час", "الساعة", "كم الساعة", "समय", "समय क्या"})),
        TemporalField("date", frozenset({"fecha", "fecha actual", "date", "datum", "data", "日付", "تاريخ"})),
    )
    QUERY_CUES = frozenset({
        "que", "cual", "dime", "decir", "dices", "indica", "indicame", "estamos", "es", "son",
        "what", "which", "tell", "is", "are", "quel", "quelle", "welcher", "che", "dimmi",
    })
    CURRENT_CUES = frozenset({"hoy", "actual", "ahora", "estamos"})
    NON_FACTUAL_OPERATIONS = frozenset({
        "resumen", "noticias", "agenda", "historia", "explica",
        "temperatura", "clima", "pronostico", "weather", "forecast",
    })
    COMPOSITION_CUES = frozenset({
        "junto", "juntos", "juntas", "ambos", "combina", "combinar", "completo",
        "together", "both", "combine", "ensemble", "zusammen", "insieme",
    })
    FIELD_ORDER = ("day", "month", "year", "time")

    def __init__(self, fields: tuple[TemporalField, ...] | None = None) -> None:
        self._fields = fields or self.DEFAULT_FIELDS

    def resolve(self, text: str, *, history: Iterable[str] = ()) -> TemporalResolution | None:
        normalized = _fold(text)
        tokens = tuple(normalized.split())
        token_set = set(tokens)
        matched: set[str] = set()
        evidence: list[str] = []
        for definition in self._fields:
            aliases = sorted(definition.aliases, key=len, reverse=True)
            alias = next((item for item in aliases if re.search(rf"(?:^| ){re.escape(item)}(?: |$)", normalized)), None)
            if alias:
                matched.add(definition.field_id)
                evidence.append(f"field:{definition.field_id}:{alias}")
        if "date" in matched:
            matched.remove("date")
            matched.update(("day", "month", "year"))
            evidence.append("date_expansion")
        query_overlap = token_set & self.QUERY_CUES
        current_overlap = token_set & self.CURRENT_CUES
        operation_overlap = token_set & self.NON_FACTUAL_OPERATIONS
        composition_overlap = token_set & self.COMPOSITION_CUES
        if not matched and composition_overlap and query_overlap:
            contextual_fields: set[str] = set()
            for previous in tuple(history)[-6:]:
                prior = self.resolve(previous)
                if prior:
                    contextual_fields.update(prior.fields)
            if contextual_fields:
                matched.update(contextual_fields)
                evidence.extend(f"context:{field}" for field in self.FIELD_ORDER if field in contextual_fields)
                evidence.extend(f"composition:{item}" for item in sorted(composition_overlap))
        if not matched:
            return None
        score = 0.48 + min(0.22, 0.08 * len(matched))
        score += 0.18 if query_overlap else 0.0
        score += 0.12 if current_overlap else 0.0
        score += 0.12 if len(tokens) <= 4 else 0.0
        score += 0.12 if composition_overlap and any(item.startswith("context:") for item in evidence) else 0.0
        score -= 0.55 if operation_overlap else 0.0
        confidence = max(0.0, min(1.0, score))
        if confidence < 0.66:
            return None
        evidence.extend(f"query:{item}" for item in sorted(query_overlap))
        evidence.extend(f"current:{item}" for item in sorted(current_overlap))
        fields = tuple(field for field in self.FIELD_ORDER if field in matched)
        return TemporalResolution(fields, confidence, tuple(evidence), "solo" in token_set)
