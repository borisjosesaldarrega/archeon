"""Lightweight knowledge-domain routing and evidence policy."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeAssessment:
    domains: tuple[str, ...]
    temporal: str
    risk: str
    requires_fresh_sources: bool
    allow_unverified_claims: bool

    def public(self) -> dict[str, object]:
        return asdict(self)


class KnowledgeRouter:
    """Classify broad human-knowledge requests without loading another model."""

    DOMAIN_TERMS = {
        "medicine": ("salud", "médic", "medic", "síntoma", "diagnóstico", "medicina", "medication", "disease"),
        "law": ("ley", "legal", "demanda", "contrato", "derecho", "regulación", "regulation", "court"),
        "finance": ("inversión", "acciones", "finanzas", "préstamo", "impuesto", "stock", "crypto", "trading"),
        "current_events": ("noticia", "última noticia", "hoy", "este año", "news", "latest", "today", "current events"),
        "science": ("física", "química", "biología", "astronomía", "fotosíntesis", "science", "physics", "chemistry", "biology"),
        "mathematics": ("matemática", "estadística", "álgebra", "cálculo", "geometría", "math", "equation", "statistics"),
        "technology": ("tecnología", "software", "hardware", "computadora", "internet", "technology", "computer"),
        "programming": ("programa", "código", "api", "html", "python", "javascript", "base de datos", "code", "debug"),
        "history": ("historia", "histórico", "siglo", "civilización", "history", "ancient"),
        "geography": ("geografía", "país", "capital", "río", "montaña", "geography", "country"),
        "arts": ("arte", "música", "pintura", "cine", "literatura", "art", "music", "film", "literature"),
        "language": ("idioma", "traduce", "gramática", "inglés", "language", "translate", "grammar"),
        "education": ("tarea", "estudiar", "enséñame", "explica", "actividad", "education", "learn", "homework"),
        "business": ("empresa", "negocio", "marketing", "ventas", "business", "market", "sales"),
        "psychology": ("psicología", "emocional", "ansiedad", "psychology", "mental health"),
        "engineering": ("ingeniería", "circuito", "mecánica", "estructura", "engineering", "circuit"),
        "environment": ("clima", "ambiente", "ecología", "climate", "environment", "ecology"),
        "sports": ("deporte", "partido", "fútbol", "liga", "sports", "score", "league"),
        "culture": ("cultura", "religión", "sociedad", "culture", "religion", "society"),
        "daily_life": ("cocina", "viaje", "hogar", "receta", "travel", "recipe", "home"),
    }
    CURRENT_PATTERN = re.compile(
        r"\b(?:hoy|ahora|actual(?:es)?|[uú]ltim[ao]s?|reciente|202[5-9]|203\d|today|now|current|latest|recent)\b",
        re.I,
    )

    def assess(self, text: str) -> KnowledgeAssessment:
        normalized = str(text).casefold()
        domains = tuple(domain for domain, terms in self.DOMAIN_TERMS.items() if any(term in normalized for term in terms)) or ("general",)
        high_risk = any(domain in {"medicine", "law", "finance"} for domain in domains)
        negated_lookup = bool(re.search(r"\b(?:no|sin)\s+(?:busques?|consultes?|quiero|necesito)\b.{0,35}\b(?:noticias?|datos?|informaci[oó]n)\b", normalized))
        changing = bool(self.CURRENT_PATTERN.search(normalized)) and not negated_lookup
        return KnowledgeAssessment(
            domains, "changing" if changing else "stable", "high" if high_risk else "normal",
            changing or high_risk, not (changing or high_risk),
        )
