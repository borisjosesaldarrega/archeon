"""Context-aware language repair that always preserves the user's raw input."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from archeon.core.language import LanguageContextEngine
from .negation import CommandConfidence, NegationScopeResolver


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class InterpretedIntent:
    raw_user_input: str
    repaired_text: str
    action: str = "respond"
    formats: tuple[str, ...] = ()
    writing_style: str | None = None
    include_evidence: bool = False
    reference: str | None = None
    confidence: Confidence = Confidence.HIGH
    clarification_required: bool = False
    reasons: tuple[str, ...] = ()
    corrections: tuple[dict[str, str], ...] = ()
    language: str | None = None

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["confidence"] = self.confidence.value
        return value


@dataclass(slots=True)
class NaturalLanguageRepair:
    """Repair only high-value task vocabulary; never rewrite the stored message."""

    _TOKEN_FIXES: dict[str, str] = field(default_factory=lambda: {
        "has": "haz", "hasme": "hazme", "aser": "hacer", "wor": "word",
        "wordd": "word", "exel": "excel", "ecsel": "excel", "pef": "pdf",
        "pedefe": "pdf", "jason": "json", "cap": "capturas", "caps": "capturas", "ablas": "hablas",
        "ablar": "hablar", "tambn": "también", "tambien": "también",
        "habre": "abre", "habras": "abras", "stin": "steam",
    })

    _negation: NegationScopeResolver = field(default_factory=NegationScopeResolver)

    @staticmethod
    def _fold(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(value.split())

    def interpret(
        self, raw_user_input: str, *, context: Any | None = None,
        known_files: Iterable[str | Path] = (), stt_confidence: float | None = None,
    ) -> InterpretedIntent:
        raw = str(raw_user_input)
        repaired = self._fold(raw)
        corrections: list[dict[str, str]] = []
        phrase_fixes = (
            (r"\bpe\s+de\s+efe\b", "pdf"), (r"\bpe\s+de\s+fe\b", "pdf"),
            (r"\bno\s+tan\s+i\s*a\b", "no tan ia"),
        )
        for pattern, replacement in phrase_fixes:
            changed, count = re.subn(pattern, replacement, repaired)
            if count:
                corrections.append({"from": pattern, "to": replacement})
                repaired = changed
        tokens = repaired.split()
        for index, token in enumerate(tokens):
            clean = token.strip(".,;:!?¡¿()[]{}")
            replacement = self._TOKEN_FIXES.get(clean)
            if replacement:
                corrections.append({"from": clean, "to": replacement})
                tokens[index] = token.replace(clean, replacement)
        repaired = " ".join(tokens)

        selected = str(getattr(context, "selected_file", "") or "")
        candidates = [str(item) for item in known_files]
        if selected:
            candidates.insert(0, selected)
        active_suffix = Path(candidates[0]).suffix.casefold() if candidates else ""

        formats: list[str] = []
        if re.search(r"\b(?:word|docx)\b", repaired): formats.append("docx")
        if re.search(r"\bpdf\b", repaired): formats.append("pdf")
        if re.search(r"\b(?:excel|xlsx)\b", repaired): formats.append("xlsx")
        if re.search(r"\b(?:powerpoint|pptx)\b", repaired): formats.append("pptx")
        if re.search(r"\bcsv\b", repaired): formats.append("csv")
        if re.search(r"\bjson\b", repaired): formats.append("json")
        if re.search(r"\bzip\b", repaired): formats.append("zip")
        if "pdf" in formats and "xlsx" in formats and active_suffix == ".xlsx":
            formats = ["pdf"]

        destructive_pattern = r"(?:\b(?:borr\w*|elimin\w*|delete|remove|supprimer|löschen|loschen|удали)\b|删除|削除|삭제|احذف|हटाओ)"
        destructive_resolution = self._negation.resolve(repaired, destructive_pattern, destructive=True)
        destructive = destructive_resolution.action_allowed
        vague_reference = bool(re.search(r"(?:\b(?:ese|esa|eso|archivo ese|documento ese|that file|that document|esse arquivo|ce fichier|diese datei|quel file|этот файл)\b|那个文件|そのファイル|그 파일|ذلك الملف|वह फ़ाइल)", repaired))
        reference = (
            "previous" if re.search(r"(?:\b(?:anterior|de ayer|previous|yesterday|anterior|hier|gestern|precedente|ieri|вчера)\b|昨天|昨日|어제|أمس|कल)", repaired) else
            "responsive" if re.search(r"\b(?:foto|captura).*(?:abajo|responsive|estrecha)\b", repaired) else
            "current" if vague_reference or re.search(r"(?:\b(?:esto|este documento|ese documento|this document|este documento|ce document|dieses dokument|questo documento|этот документ)\b|这个文档|この文書|이 문서|هذا المستند|यह दस्तावेज़)", repaired) else None
        )
        def resolved(pattern: str, *, destructive_action: bool = False) -> bool:
            resolution = self._negation.resolve(
                repaired, pattern, context_present=bool(candidates), destructive=destructive_action,
            )
            # This layer classifies intent; it does not execute it. Explicit
            # non-destructive verbs remain useful in SOV languages (PDFを作成)
            # and after polite prefixes that are not Spanish. Negation still
            # blocks the intent, while destructive actions retain the stricter gate.
            return resolution.action_allowed or bool(
                not destructive_action
                and not resolution.negated
                and resolution.confidence is CommandConfidence.AMBIGUOUS
                and resolution.matched_text
            )

        inspect_archive = resolved(r"(?:\b(?:mira|revisa|qu[eé] (?:hay|contiene)|inspect|review|what is in|verifique|regarde|prüfe|controlla|проверь)\b|查看|確認|확인|افحص|जाँच).*(?:zip|rar|7z|comprimido|archive|archiv|архив)")
        extract = resolved(r"(?:\b(?:extrae\w*|extract|extrair|extraire|entpacken|estrai|извлеки)\b|解压|展開|압축 해제|استخرج|निकालो)")
        convert = resolved(r"(?:\b(?:p[aá]sa(?:me|lo|la)?|conviert\w*|convert|transforme|converta|convertis|umwandeln|converti|преобразуй)\b|转换|変換|변환|حوّل|बदलें)")
        create = resolved(r"(?:\b(?:haz(?:me|lo|la)?|crea\w*|genera\w*|create|make|generate|crie|faça|cree|crée|erstelle|создай)\b|创建|作成|만들|أنشئ|बनाओ)")
        edit = resolved(r"(?:\b(?:pon(?:le|lo|la)?|cambia\w*|corrige\w*|quita\w*|edit|change|fix|edite|modifie|ändere|bearbeite|modifica|исправь)\b|编辑|修正|편집|수정|عدّل|संपादित)")
        action = "delete" if destructive else "inspect_archive" if inspect_archive else "extract" if extract else "convert" if convert else "create" if create else "edit" if edit else "respond"
        include_evidence = bool(re.search(r"\b(?:capturas?|fotos?|evidencias?)\b", repaired))
        style = "student" if re.search(r"\b(?:estudiante|estudiantil|no tan ia|m[aá]s humano|natural)\b", repaired) else None

        reasons: list[str] = []
        confidence = Confidence.HIGH
        clarification = False
        if destructive and (vague_reference or not candidates):
            confidence = Confidence.LOW; clarification = True
            reasons.append("destructive_reference_is_ambiguous")
        elif destructive_resolution.confidence is CommandConfidence.NEGATED:
            reasons.append(destructive_resolution.reason)
        elif corrections and not candidates and action in {"convert", "edit"}:
            confidence = Confidence.MEDIUM
            reasons.append("repaired_action_without_verified_target")
        if stt_confidence is not None:
            if stt_confidence < 0.45:
                confidence = Confidence.LOW; clarification = True
                reasons.append("low_stt_confidence")
            elif stt_confidence < 0.70 and confidence is Confidence.HIGH:
                confidence = Confidence.MEDIUM
                reasons.append("medium_stt_confidence")
        if active_suffix and action in {"convert", "edit"}:
            reasons.append(f"active_document:{active_suffix.lstrip('.')}")

        return InterpretedIntent(
            raw_user_input=raw, repaired_text=repaired, action=action,
            formats=tuple(dict.fromkeys(formats)), writing_style=style,
            include_evidence=include_evidence, reference=reference,
            confidence=confidence, clarification_required=clarification,
            reasons=tuple(reasons), corrections=tuple(corrections),
            language=LanguageContextEngine().detect(raw),
        )
