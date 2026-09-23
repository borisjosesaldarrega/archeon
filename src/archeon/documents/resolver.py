"""Bounded, evidence-based local document resolution for text and voice requests."""

from __future__ import annotations

import re
import os
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from archeon.agent.task import TaskContext

from .reader import DocumentReader


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(ch for ch in normalized if not unicodedata.combining(ch)).split())


@dataclass(frozen=True, slots=True)
class DocumentCandidate:
    path: Path
    score: float
    reason: str
    modified: float

    def public(self) -> dict[str, object]:
        stat = self.path.stat()
        return {
            "name": self.path.name, "path": str(self.path), "extension": self.path.suffix.lstrip("."),
            "bytes": stat.st_size, "modified": self.modified, "score": round(self.score, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DocumentResolution:
    status: str
    selected: DocumentCandidate | None
    candidates: tuple[DocumentCandidate, ...]
    visited: int = 0

    @property
    def ambiguous(self) -> bool:
        return self.status == "ambiguous"


class DocumentResolver:
    MAX_VISITED = 5000
    MAX_RESULTS = 20
    REFERENCE_WORDS = re.compile(r"\b(?:esto|este|ese|esa|documento|archivo|pdf|docx|p[aá]gina|anterior|res[uú]melo|l[eé]elo)\b")

    @staticmethod
    def windows_selected_files() -> tuple[Path, ...]:
        """Read Explorer selection only on demand; no shell polling or resident COM object."""
        if os.name != "nt":
            return ()
        try:
            import comtypes.client

            shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
            selected: list[Path] = []
            for window in shell.Windows():
                try:
                    for item in window.Document.SelectedItems():
                        path = Path(str(item.Path)).expanduser().resolve()
                        if path.is_file():
                            selected.append(path)
                except Exception:
                    continue
            return tuple(dict.fromkeys(selected))
        except Exception:
            return ()

    def resolve(
        self, request: str, *, context: TaskContext, roots: Iterable[Path] = (),
        attached_paths: Iterable[Path] = (),
    ) -> DocumentResolution:
        query = _plain(request)
        ordinal_match = re.search(r"\b(?:el|la)?\s*(primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta)\b", query)
        if ordinal_match:
            index = {"primero": 0, "primera": 0, "segundo": 1, "segunda": 1, "tercero": 2, "tercera": 2, "cuarto": 3, "cuarta": 3, "quinto": 4, "quinta": 4}[ordinal_match.group(1)]
            pending = [item for item in context.recent_entities if item.get("kind") == "document_candidate" and item.get("path")]
            if index < len(pending):
                path = Path(str(pending[index]["path"])).expanduser().resolve()
                if path.is_file():
                    candidate = DocumentCandidate(path, 1.0, "disambiguation_choice", path.stat().st_mtime)
                    return DocumentResolution("selected", candidate, (candidate,), 1)
        attachments = [path.resolve() for path in attached_paths if path.is_file()]
        if attachments:
            candidates = tuple(DocumentCandidate(path, 1.0, "attachment", path.stat().st_mtime) for path in attachments)
            if len(candidates) == 1:
                return DocumentResolution("selected", candidates[0], candidates, len(candidates))
            return DocumentResolution("ambiguous", None, candidates, len(candidates))

        previous = "anterior" in query
        remembered = context.referenced_document("previous" if previous else "current")
        if remembered and self.REFERENCE_WORDS.search(query):
            path = Path(remembered).expanduser().resolve()
            if path.is_file():
                candidate = DocumentCandidate(path, 1.0, "task_context", path.stat().st_mtime)
                return DocumentResolution("selected", candidate, (candidate,), 1)

        extension_match = re.search(r"\b(pdf|docx|xlsx|pptx|txt|md|csv|json|html|zip|7z|rar|tar)\b", query)
        wanted_extension = "." + extension_match.group(1) if extension_match else ""
        yesterday = "ayer" in query
        day_start = (datetime.now().astimezone() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400
        active_title = _plain(context.active_window or "")
        terms = self._query_terms(query)
        candidates: list[DocumentCandidate] = []
        visited = 0
        seen: set[Path] = set()
        for root in roots:
            scope = Path(root).expanduser().resolve()
            if not scope.is_dir() or scope == Path(scope.anchor):
                continue
            for path in scope.rglob("*"):
                visited += 1
                if visited > self.MAX_VISITED:
                    break
                if not path.is_file() or path.suffix.casefold() not in DocumentReader.SUPPORTED | {".xlsx", ".pptx", ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}:
                    continue
                resolved = path.resolve()
                if resolved in seen or (wanted_extension and path.suffix.casefold() != wanted_extension):
                    continue
                seen.add(resolved)
                modified = path.stat().st_mtime
                if yesterday and not (day_start <= modified < day_end):
                    continue
                stem = _plain(path.stem)
                score = self._score(terms, stem)
                reason = "fuzzy_name"
                if terms and terms == stem:
                    score, reason = 1.0, "exact_name"
                if active_title and (stem in active_title or active_title in stem):
                    score, reason = max(score, 0.96), "active_window"
                if yesterday:
                    score += 0.08
                    reason += "+date"
                if not terms:
                    score = max(score, 0.55 + min(0.2, max(0.0, (modified - (time.time() - 604800)) / 6048000)))
                    reason = "recent"
                if score >= 0.34:
                    candidates.append(DocumentCandidate(resolved, min(score, 1.0), reason, modified))
            if visited > self.MAX_VISITED:
                break
        candidates.sort(key=lambda item: (item.score, item.modified), reverse=True)
        bounded = tuple(candidates[: self.MAX_RESULTS])
        if not bounded:
            return DocumentResolution("not_found", None, (), visited)
        if len(bounded) > 1 and bounded[0].score - bounded[1].score < 0.08:
            return DocumentResolution("ambiguous", None, bounded, visited)
        return DocumentResolution("selected", bounded[0], bounded, visited)

    @staticmethod
    def _query_terms(query: str) -> str:
        value = re.sub(
            r"\b(?:archeon|busca|buscar|encuentra|abre|abrir|lee|leer|archivo|documento|pdf|docx|xlsx|pptx|txt|md|csv|json|html|"
            r"zip|7z|rar|tar|comprimido|que|el|la|los|las|un|una|mi|en|de|descargas|downloads|descargue|descargado|ayer|tengo|abierto|seleccionado|reciente)\b",
            " ", query,
        )
        return " ".join(value.split()).strip(" .,_-")

    @staticmethod
    def _score(query: str, stem: str) -> float:
        if not query:
            return 0.0
        if query in stem or stem in query:
            return 0.92
        query_tokens, stem_tokens = set(query.split()), set(stem.split())
        overlap = len(query_tokens & stem_tokens) / max(1, len(query_tokens | stem_tokens))
        return 0.65 * SequenceMatcher(None, query, stem).ratio() + 0.35 * overlap
