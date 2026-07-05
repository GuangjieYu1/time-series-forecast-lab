from __future__ import annotations

import os
import time

try:
    import resource
except ImportError:  # pragma: no cover - Windows only
    resource = None


def now() -> float:
    return time.perf_counter()


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 4)


def max_rss_mb() -> float:
    if resource is not None:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if value > 1024 * 1024:
            return round(value / 1024 / 1024, 2)
        return round(value / 1024, 2)

    import ctypes
    from ctypes import wintypes

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
    handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
    if not handle:
        return 0.0
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return round(counters.PeakWorkingSetSize / 1024 / 1024, 2) if ok else 0.0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
