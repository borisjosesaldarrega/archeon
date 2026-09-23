from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from archeon.learning import LearningScope, LearningSource, OperationalLearningEngine


def test_explicit_correction_is_active_scoped_and_persistent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "learning.json"
        engine = OperationalLearningEngine(path)
        record = engine.record_correction(
            phrase="ponme un ejemplo", wrong_intent="media", correct_intent="conversation",
            reason="Example is educational without explicit music context",
            source=LearningSource.USER_EXPLICIT, scope=LearningScope.USER, scope_id="boris",
        )
        assert record.active and record.confidence.value == "high"
        assert engine.match("por favor ponme un ejemplo", user_id="boris") is not None
        assert engine.match("ponme un ejemplo", user_id="other") is None
        assert OperationalLearningEngine(path).match("ponme un ejemplo", user_id="boris").id == record.id


def test_inference_needs_repetition_and_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        engine = OperationalLearningEngine(Path(directory) / "learning.json")
        first = engine.record_correction(
            phrase="hazlo breve", wrong_intent="verbose", correct_intent="concise", reason="Observed preference",
            source=LearningSource.INFERRED, scope=LearningScope.PROJECT, scope_id=directory,
            evidence=({"kind": "accepted_result"},),
        )
        assert not first.active
        second = engine.record_correction(
            phrase="hazlo breve", wrong_intent="verbose", correct_intent="concise", reason="Repeated preference",
            source=LearningSource.INFERRED, scope=LearningScope.PROJECT, scope_id=directory,
            evidence=({"kind": "accepted_result"},),
        )
        assert second.active and second.occurrences == 2


def test_bad_evidence_and_uncontrolled_regression_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        engine = OperationalLearningEngine(Path(directory) / "learning.json")
        with pytest.raises(ValueError, match="untrusted_learning_evidence"):
            engine.record_correction(
                phrase="x", wrong_intent="a", correct_intent="b", reason="bad",
                source=LearningSource.TOOL_VERIFICATION, scope=LearningScope.GLOBAL,
                evidence=({"kind": "tool_crash"},), verified=True,
            )
        record = engine.record_correction(
            phrase="no esa versión", wrong_intent="repeat_track", correct_intent="reject_media_version",
            reason="Explicit rejection", source=LearningSource.USER_EXPLICIT, scope=LearningScope.GLOBAL,
        )
        candidate = engine.regression_candidate(record.id, "topic_hijacking")
        assert candidate["auto_apply"] is False
        assert engine.forget(record.id)
        assert engine.list_records() == []
