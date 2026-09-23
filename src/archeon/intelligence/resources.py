"""Low-overhead memory pressure checks before loading optional AI runtimes."""

from __future__ import annotations

import ctypes
import os
from dataclasses import asdict, dataclass
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    total_bytes: int
    available_bytes: int
    load_percent: float

    def public(self) -> dict[str, int | float]:
        return asdict(self)


def system_memory_snapshot() -> MemorySnapshot:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("memory_status_unavailable")
        return MemorySnapshot(int(status.ullTotalPhys), int(status.ullAvailPhys), float(status.dwMemoryLoad))
    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
    available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
    return MemorySnapshot(total, available, 100.0 * (1.0 - available / max(1, total)))


class MemoryPressureGuard:
    """Unload ARCHEON-owned optional components before refusing an unsafe load.

    It never closes user applications, never polls in the background and only
    samples memory when an optional model is about to be loaded.
    """

    def __init__(
        self,
        minimum_available_bytes: int,
        *,
        releasers: Iterable[Callable[[], object]] = (),
        sampler: Callable[[], MemorySnapshot] = system_memory_snapshot,
    ) -> None:
        self.minimum_available_bytes = max(0, int(minimum_available_bytes))
        self._releasers = tuple(releasers)
        self._sampler = sampler
        self._last: MemorySnapshot | None = None
        self._released = 0

    def prepare(self) -> MemorySnapshot:
        snapshot = self._sampler()
        self._last = snapshot
        if snapshot.available_bytes >= self.minimum_available_bytes:
            return snapshot
        for release in self._releasers:
            try:
                release()
                self._released += 1
            except Exception:
                continue
        snapshot = self._sampler()
        self._last = snapshot
        if snapshot.available_bytes < self.minimum_available_bytes:
            raise MemoryError("insufficient_memory_for_local_ai")
        return snapshot

    def status(self) -> dict[str, object]:
        return {
            "minimum_available_bytes": self.minimum_available_bytes,
            "released_components": self._released,
            "last_snapshot": self._last.public() if self._last else None,
        }
