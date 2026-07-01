from __future__ import annotations

import resource
import time


def now() -> float:
    return time.perf_counter()


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 4)


def max_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if value > 1024 * 1024:
        return round(value / 1024 / 1024, 2)
    return round(value / 1024, 2)
