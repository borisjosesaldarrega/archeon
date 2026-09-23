"""Conservative guards for deterministic intent routing.

Fast paths must have higher precision than generative routing: a missed fast
path can still be understood by ARCHI, while a false positive may execute the
wrong deterministic action.
"""

from __future__ import annotations

import re
from typing import Pattern


_NEGATION = re.compile(
    r"(?:\b(?:no|nunca|jam[aá]s|sin|evita|evitar|dont|don't|do not|never|without|"
    r"n[aã]o|ne|pas|nicht|kein|non|senza|не|без)\b|不要|别|しない|하지\s*마|لا|मत)",
    re.IGNORECASE,
)

_CONTRAST = re.compile(r"(?:[,;:]|\b(?:pero|sino|aunque|however|but|por[eé]m|mas|aber|tuttavia)\b)", re.IGNORECASE)


def has_unnegated(pattern: str | Pattern[str], text: str, *, lookbehind_words: int = 4) -> bool:
    compiled = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
    for match in compiled.finditer(text):
        words = re.findall(r"\S+", text[:match.start()])[-max(1, lookbehind_words):]
        context = " ".join(words)
        contrasts = list(_CONTRAST.finditer(context))
        if contrasts:
            context = context[contrasts[-1].end():]
        if not _NEGATION.search(context):
            return True
    return False


def is_current_information_request(text: str) -> bool:
    value = " ".join(text.casefold().split())
    if re.search(
        r"\b(?:no|nunca|never|don't|do not|n[aã]o)\s+(?:me\s+)?"
        r"(?:busques|investigues|consultes|verifiques|search|look up|pesquise)\b.{0,36}"
        r"(?:noticias|actualidad|news|current events)",
        value,
    ):
        return False
    exact_news = {
        "noticias", "actualidad", "latest news", "current events", "news today",
        "noticias atuais", "actualités", "actualites", "nachrichten", "notizie attuali",
        "最新消息", "最新ニュース", "최신 뉴스", "последние новости", "آخر الأخبار", "ताज़ा खबरें",
    }
    if value.strip(" .!?¡¿") in exact_news or re.search(
        r"(?:\b(?:noticias|news)\s+(?:de\s+)?hoy\b|\b(?:latest news|current events|news today|"
        r"noticias atuais|actualit[eé]s|notizie attuali)\b|最新消息|最新ニュース|최신 뉴스|"
        r"последние новости|آخر الأخبار|ताज़ा खबरें)", value,
    ):
        return True
    # Named leaks, hacks and announcements are event-sensitive even when the
    # speaker omits "latest" or "today". Verify them instead of trusting the
    # local model's training snapshot.
    if re.search(
        r"\b(?:qu[eé]\s+sabes|cu[eé]ntame|informaci[oó]n|what do you know|tell me)\b"
        r".{0,72}\b(?:hacker|hackeo|filtraci[oó]n|leak|anuncio|lanzamiento)\b",
        value,
    ):
        return True
    return bool(re.search(
        r"\b(?:qu[eé]|cu[aá]l|dime|busca|consulta|verifica|informaci[oó]n|what|find|check)\b"
        r".{0,48}\b(?:hoy|ahora|actual(?:es)?|reciente(?:s)?|este a[nñ]o|202[5-9])\b|"
        r"\b(?:qu[eé]\s+pas[oó]|what happened)\s+hoy\b",
        value,
    ))


def is_product_help_request(text: str) -> bool:
    value = " ".join(text.casefold().split())
    if re.search(r"\b(?:d[oó]nde est[aá] tu (?:cerebro|coraz[oó]n)|c[oó]mo funcionas por dentro)\b", value):
        return True
    help_pattern = (
        r"\b(?:c[oó]mo (?:cambio|cambiar|configuro|configurar)|d[oó]nde (?:cambio|configuro)|"
        r"ayuda con|how do i (?:change|configure)|where do i change|como (?:altero|configurar)|"
        r"comment modifier|wie [aä]ndere ich|come modifico)\b"
    )
    help_form = has_unnegated(help_pattern, value)
    product_anchor = re.search(
        r"\b(?:archeon|archi|asistente|tus? ajustes|tu configuraci[oó]n|orbe|ghost|wake word|"
        r"palabra de activaci[oó]n)\b",
        value,
    )
    return bool(help_form and product_anchor)


def is_ambiguous_media_play_verb(verb: str) -> bool:
    return " ".join(verb.casefold().split()) in {
        "pon", "ponme", "toca", "toque", "joue", "lis", "spiele", "metti",
    }


def has_explicit_media_context(text: str) -> bool:
    value = " ".join(text.casefold().split())
    return bool(re.search(
        r"(?:\b(?:m[uú]sica|canci[oó]n|tema musical|pista|reproducci[oó]n|music|song|track|"
        r"chanson|musique|musik|lied|musica|brano|playlist)\b|音乐|歌曲|音楽|曲|음악|노래|"
        r"موسيقى|أغنية|संगीत|गाना)", value,
    ))
