"""Learn verified operational corrections without changing model weights or Core code."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


class LearningSource(StrEnum):
    USER_EXPLICIT = "user_explicit"
    ACCEPTED_RESULT = "accepted_result"
    REJECTED_RESULT = "rejected_result"
    TEST_REGRESSION = "test_regression"
    DOCUMENT_QA = "document_qa"
    TOOL_VERIFICATION = "tool_verification"
    STT_CORRECTION = "stt_correction"
    PROJECT_VERIFICATION = "project_verification"
    INFERRED = "inferred"


class LearningConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LearningScope(StrEnum):
    GLOBAL = "global"
    USER = "user"
    DEVICE = "device"
    PROJECT = "project"


HIGH_CONFIDENCE_SOURCES = {
    LearningSource.USER_EXPLICIT, LearningSource.TEST_REGRESSION,
    LearningSource.DOCUMENT_QA, LearningSource.PROJECT_VERIFICATION,
}
VERIFICATION_SOURCES = HIGH_CONFIDENCE_SOURCES | {
    LearningSource.ACCEPTED_RESULT, LearningSource.REJECTED_RESULT,
    LearningSource.TOOL_VERIFICATION, LearningSource.STT_CORRECTION,
}
FORBIDDEN_EVIDENCE = {
    "tool_crash", "malformed_result", "unverified_external_information",
    "temporary_debug_workaround",
}
REGRESSION_CATEGORIES = {
    "media_false_positive", "topic_hijacking", "wrong_language",
    "bad_project_structure", "unsaved_personalization", "incorrect_tool_execution",
}


def _clean(value: str, limit: int) -> str:
    return " ".join(str(value).strip().split())[:limit]


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold(), flags=re.UNICODE).split())


@dataclass(slots=True)
class LearningRecord:
    phrase: str
    wrong_intent: str
    correct_intent: str
    reason: str
    source: LearningSource
    confidence: LearningConfidence
    scope: LearningScope
    scope_id: str = ""
    context_tags: tuple[str, ...] = ()
    replacement_text: str = ""
    evidence: tuple[dict[str, Any], ...] = ()
    verified: bool = False
    occurrences: int = 1
    active: bool = False
    id: str = ""
    created_at: float = field(default_factory=time.time)
    last_verified: float | None = None

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["source"] = self.source.value
        value["confidence"] = self.confidence.value
        value["scope"] = self.scope.value
        return value


class OperationalLearningEngine:
    """Small JSON-backed correction memory with strict trust and scope boundaries."""

    def __init__(self, path: Path, *, maximum_records: int = 500) -> None:
        self.path = path.resolve()
        self.maximum_records = max(20, min(5000, int(maximum_records)))
        self._lock = RLock()

    @staticmethod
    def _confidence(source: LearningSource) -> LearningConfidence:
        if source in HIGH_CONFIDENCE_SOURCES:
            return LearningConfidence.HIGH
        if source in VERIFICATION_SOURCES:
            return LearningConfidence.MEDIUM
        return LearningConfidence.LOW

    @staticmethod
    def _identifier(phrase: str, wrong_intent: str, correct_intent: str, scope: LearningScope, scope_id: str) -> str:
        payload = "\0".join((_normalized(phrase), wrong_intent.casefold(), correct_intent.casefold(), scope.value, scope_id.casefold()))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def record_correction(
        self, *, phrase: str, wrong_intent: str, correct_intent: str, reason: str,
        source: LearningSource | str, scope: LearningScope | str,
        scope_id: str = "", context_tags: Iterable[str] = (), replacement_text: str = "",
        evidence: Iterable[dict[str, Any]] = (), verified: bool = False,
    ) -> LearningRecord:
        source = LearningSource(source); scope = LearningScope(scope)
        phrase = _clean(phrase, 500); wrong_intent = _clean(wrong_intent, 80)
        correct_intent = _clean(correct_intent, 80); reason = _clean(reason, 500)
        scope_id = _clean(scope_id, 260); replacement_text = _clean(replacement_text, 1000)
        if not phrase or not correct_intent or not reason:
            raise ValueError("learning_phrase_intent_reason_required")
        if scope is not LearningScope.GLOBAL and not scope_id:
            raise ValueError("learning_scope_id_required")
        sanitized_evidence = tuple(dict(item) for item in evidence if isinstance(item, dict))[:20]
        evidence_kinds = {str(item.get("kind", "")).casefold() for item in sanitized_evidence}
        if evidence_kinds & FORBIDDEN_EVIDENCE:
            raise ValueError("untrusted_learning_evidence")
        if source not in VERIFICATION_SOURCES and verified:
            raise ValueError("inferred_learning_cannot_self_verify")
        record_id = self._identifier(phrase, wrong_intent, correct_intent, scope, scope_id)
        records = self.list_records(include_inactive=True)
        existing = next((item for item in records if item.id == record_id), None)
        occurrences = min(1000, (existing.occurrences if existing else 0) + 1)
        trusted = bool(verified and source in VERIFICATION_SOURCES)
        active = source is LearningSource.USER_EXPLICIT or trusted or (source is LearningSource.INFERRED and occurrences >= 2 and bool(sanitized_evidence))
        now = time.time()
        record = LearningRecord(
            phrase=phrase, wrong_intent=wrong_intent, correct_intent=correct_intent,
            reason=reason, source=source, confidence=self._confidence(source), scope=scope,
            scope_id=scope_id, context_tags=tuple(sorted({_clean(item, 80).casefold() for item in context_tags if _clean(item, 80)}))[:20],
            replacement_text=replacement_text, evidence=sanitized_evidence, verified=trusted,
            occurrences=occurrences, active=active, id=record_id,
            created_at=existing.created_at if existing else now,
            last_verified=now if trusted or source is LearningSource.USER_EXPLICIT else (existing.last_verified if existing else None),
        )
        records = [item for item in records if item.id != record_id]
        records.append(record)
        self._write(records[-self.maximum_records:])
        return record

    def match(
        self, phrase: str, *, user_id: str = "", device_id: str = "",
        project_root: str = "", context_tags: Iterable[str] = (),
    ) -> LearningRecord | None:
        normalized = _normalized(phrase)
        tags = {_clean(item, 80).casefold() for item in context_tags}
        matches: list[LearningRecord] = []
        for record in self.list_records():
            if _normalized(record.phrase) not in normalized:
                continue
            if record.scope is LearningScope.USER and record.scope_id != user_id:
                continue
            if record.scope is LearningScope.DEVICE and record.scope_id != device_id:
                continue
            if record.scope is LearningScope.PROJECT and Path(record.scope_id) != Path(project_root):
                continue
            if record.context_tags and not set(record.context_tags).issubset(tags):
                continue
            matches.append(record)
        if not matches:
            return None
        scope_rank = {LearningScope.PROJECT: 4, LearningScope.USER: 3, LearningScope.DEVICE: 2, LearningScope.GLOBAL: 1}
        confidence_rank = {LearningConfidence.HIGH: 3, LearningConfidence.MEDIUM: 2, LearningConfidence.LOW: 1}
        return max(matches, key=lambda item: (scope_rank[item.scope], confidence_rank[item.confidence], len(item.phrase), item.last_verified or 0))

    def forget(self, record_id: str) -> bool:
        records = self.list_records(include_inactive=True)
        remaining = [item for item in records if item.id != record_id]
        if len(remaining) == len(records):
            return False
        self._write(remaining)
        return True

    def reset(self, *, scope: LearningScope | str, scope_id: str = "") -> int:
        scope = LearningScope(scope)
        records = self.list_records(include_inactive=True)
        remaining = [item for item in records if not (item.scope is scope and (not scope_id or item.scope_id == scope_id))]
        removed = len(records) - len(remaining)
        self._write(remaining)
        return removed

    def regression_candidate(self, record_id: str, category: str) -> dict[str, Any]:
        if category not in REGRESSION_CATEGORIES:
            raise ValueError("unsupported_regression_category")
        record = next((item for item in self.list_records() if item.id == record_id), None)
        if record is None or not record.verified and record.source is not LearningSource.USER_EXPLICIT:
            raise ValueError("verified_learning_required")
        return {
            "kind": "regression_candidate", "category": category, "learning_id": record.id,
            "phrase": record.phrase, "expected_intent": record.correct_intent,
            "reason": record.reason, "auto_apply": False,
        }

    def list_records(self, *, include_inactive: bool = False) -> list[LearningRecord]:
        if not self.path.is_file():
            return []
        try:
            with self._lock:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = [self._decode(item) for item in payload if isinstance(item, dict)]
            return records if include_inactive else [item for item in records if item.active]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _write(self, records: Iterable[LearningRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = [item.public() for item in records]
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    @staticmethod
    def _decode(value: dict[str, Any]) -> LearningRecord:
        return LearningRecord(
            phrase=str(value.get("phrase", "")), wrong_intent=str(value.get("wrong_intent", "")),
            correct_intent=str(value.get("correct_intent", "")), reason=str(value.get("reason", "")),
            source=LearningSource(value.get("source", LearningSource.INFERRED.value)),
            confidence=LearningConfidence(value.get("confidence", LearningConfidence.LOW.value)),
            scope=LearningScope(value.get("scope", LearningScope.GLOBAL.value)), scope_id=str(value.get("scope_id", "")),
            context_tags=tuple(str(item) for item in value.get("context_tags", ())),
            replacement_text=str(value.get("replacement_text", "")),
            evidence=tuple(dict(item) for item in value.get("evidence", ()) if isinstance(item, dict)),
            verified=bool(value.get("verified", False)), occurrences=max(1, int(value.get("occurrences", 1))),
            active=bool(value.get("active", False)), id=str(value.get("id", "")),
            created_at=float(value.get("created_at", time.time())),
            last_verified=float(value["last_verified"]) if value.get("last_verified") is not None else None,
        )
