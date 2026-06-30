from __future__ import annotations

import os
import re
import subprocess


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


def _read_linux_meminfo() -> dict[str, int | None]:
    total_mb: int | None = None
    available_mb: int | None = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total_mb = int(line.split()[1]) // 1024
                if line.startswith("MemAvailable:"):
                    available_mb = int(line.split()[1]) // 1024
    except Exception:
        pass
    return {"total": total_mb, "available": available_mb}


def _run_command(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(args, check=True, capture_output=True, text=True, timeout=2)
    except Exception:
        return None
    return completed.stdout.strip()


def _read_macos_total_mb() -> int | None:
    output = _run_command(["sysctl", "-n", "hw.memsize"])
    if not output:
        return None
    try:
        return int(output) // 1024 // 1024
    except ValueError:
        return None


def _read_macos_available_mb() -> int | None:
    output = _run_command(["vm_stat"])
    if not output:
        return None
    page_size_match = re.search(r"page size of (\d+) bytes", output)
    page_size = int(page_size_match.group(1)) if page_size_match else 4096
    pages: dict[str, int] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        number = re.sub(r"[^0-9]", "", value)
        if number:
            pages[key.strip()] = int(number)
    available_pages = (
        pages.get("Pages free", 0)
        + pages.get("Pages inactive", 0)
        + pages.get("Pages speculative", 0)
        + pages.get("Pages purgeable", 0)
    )
    if available_pages <= 0:
        return None
    return int(available_pages * page_size / 1024 / 1024)


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

    linux_memory = _read_linux_meminfo()
    if linux_memory["total"] is not None:
        total_mb = linux_memory["total"]
    if linux_memory["available"] is not None:
        available_mb = linux_memory["available"]

    if total_mb is None:
        total_mb = _read_macos_total_mb()
    if available_mb is None:
        available_mb = _read_macos_available_mb()
    return {"memoryTotalMb": total_mb, "memoryAvailableMb": available_mb}
