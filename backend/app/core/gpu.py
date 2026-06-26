from __future__ import annotations

import os


def get_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        return "cpu"
    return "cpu"


def _read_mem_available_mb() -> int | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def get_memory_info() -> dict[str, int | None]:
    total_mb: int | None = None
    available_mb: int | None = None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        total_mb = int(page_size * total_pages / 1024 / 1024)
        available_mb = int(page_size * available_pages / 1024 / 1024)
    except Exception:
        pass
    proc_available = _read_mem_available_mb()
    if proc_available is not None:
        available_mb = proc_available
    return {"memoryTotalMb": total_mb, "memoryAvailableMb": available_mb}
