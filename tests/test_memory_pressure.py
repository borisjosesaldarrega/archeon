from __future__ import annotations

import pytest

from archeon.intelligence import MemoryPressureGuard, MemorySnapshot, system_memory_snapshot


def test_system_memory_snapshot_is_sane() -> None:
    snapshot = system_memory_snapshot()
    assert snapshot.total_bytes > 0
    assert 0 <= snapshot.available_bytes <= snapshot.total_bytes
    assert 0 <= snapshot.load_percent <= 100


def test_guard_releases_archi_component_and_rechecks() -> None:
    values = iter((MemorySnapshot(100, 10, 90), MemorySnapshot(100, 60, 40)))
    released: list[bool] = []
    guard = MemoryPressureGuard(50, releasers=(lambda: released.append(True),), sampler=lambda: next(values))
    assert guard.prepare().available_bytes == 60
    assert released == [True]
    assert guard.status()["released_components"] == 1


def test_guard_refuses_load_when_pressure_remains() -> None:
    guard = MemoryPressureGuard(50, sampler=lambda: MemorySnapshot(100, 10, 90))
    with pytest.raises(MemoryError, match="insufficient_memory_for_local_ai"):
        guard.prepare()
