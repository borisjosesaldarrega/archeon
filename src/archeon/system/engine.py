"""Small, read-only system primitives without psutil or background polling."""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from ctypes import wintypes
from typing import Any, Mapping

from archeon.core.lifecycle import ManagedComponent
from archeon.core.permissions import RiskLevel
from archeon.core.tools import ToolContext, ToolEngine, ToolManifest, ToolResult


SYSTEM_STATUS_MANIFEST = ToolManifest(
    id="system.status",
    description="Read basic local CPU, memory and operating-system status",
    permissions=(),
    risk=RiskLevel.READ_ONLY,
)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_memory() -> dict[str, int]:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return {
        "total_bytes": int(status.ullTotalPhys),
        "available_bytes": int(status.ullAvailPhys),
        "used_percent": int(status.dwMemoryLoad),
    }


def _process_rss() -> int | None:
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return None
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss if sys.platform == "darwin" else rss * 1024)
    except (ImportError, OSError):
        return None


def system_snapshot() -> dict[str, Any]:
    memory = _windows_memory() if sys.platform == "win32" else {}
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "memory": memory,
        "process": {"pid": os.getpid(), "working_set_bytes": _process_rss()},
    }


class SystemStatusTool:
    manifest = SYSTEM_STATUS_MANIFEST

    def execute(self, context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
        return ToolResult(True, data=system_snapshot())

    def verify(self, context: ToolContext, result: ToolResult) -> bool:
        return bool(result.data.get("logical_cpu_count") and result.data.get("platform"))


class DeviceSystemEngine(ManagedComponent):
    def __init__(self, tools: ToolEngine) -> None:
        super().__init__("device_system")
        self._tools = tools

    def _start(self) -> None:
        self._tools.register(SYSTEM_STATUS_MANIFEST, SystemStatusTool)

    def _stop(self) -> None:
        self._tools.unregister(SYSTEM_STATUS_MANIFEST.id)
