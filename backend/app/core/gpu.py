from __future__ import annotations

import contextlib
import ctypes
import io
import os
import re
import subprocess
from ctypes import wintypes
from typing import Any


def _run_command(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(args, check=True, capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return completed.stdout.strip()


def _detect_nvidia_hardware() -> dict[str, Any] | None:
    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return None
    first_line = output.splitlines()[0]
    parts = [part.strip() for part in first_line.split(",")]
    if not parts or not parts[0]:
        return None
    memory_mb = None
    if len(parts) > 1:
        try:
            memory_mb = int(float(parts[1]))
        except ValueError:
            memory_mb = None
    return {
        "name": parts[0],
        "memoryTotalMb": memory_mb,
        "driverVersion": parts[2] if len(parts) > 2 and parts[2] else None,
    }


def _torch_capabilities() -> dict[str, Any]:
    result: dict[str, Any] = {
        "installed": False,
        "version": None,
        "build": None,
        "cudaRuntime": None,
        "cudaAvailable": False,
        "mpsAvailable": False,
        "deviceName": None,
        "deviceMemoryMb": None,
    }
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import torch
    except Exception:
        return result

    result["installed"] = True
    result["version"] = str(getattr(torch, "__version__", "unknown"))
    result["cudaRuntime"] = getattr(getattr(torch, "version", None), "cuda", None)
    result["build"] = "cuda" if result["cudaRuntime"] else "cpu"
    try:
        result["cudaAvailable"] = bool(torch.cuda.is_available())
        if result["cudaAvailable"]:
            result["deviceName"] = str(torch.cuda.get_device_name(0))
            properties = torch.cuda.get_device_properties(0)
            result["deviceMemoryMb"] = int(properties.total_memory / 1024 / 1024)
    except Exception:
        result["cudaAvailable"] = False
    try:
        result["mpsAvailable"] = bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
    except Exception:
        result["mpsAvailable"] = False
    return result


def get_device_info() -> dict[str, Any]:
    memory = get_memory_info()
    nvidia = _detect_nvidia_hardware()
    torch_info = _torch_capabilities()

    if torch_info["cudaAvailable"]:
        device = "cuda"
        accelerator_type = "nvidia"
        hardware_detected = True
        runtime_available = True
        name = torch_info["deviceName"] or (nvidia or {}).get("name")
        accelerator_memory = torch_info["deviceMemoryMb"] or (nvidia or {}).get("memoryTotalMb")
        reason = None
    elif torch_info["mpsAvailable"]:
        device = "mps"
        accelerator_type = "mps"
        hardware_detected = True
        runtime_available = True
        name = "Apple Silicon GPU"
        accelerator_memory = None
        reason = None
    else:
        device = "cpu"
        accelerator_type = "nvidia" if nvidia else None
        hardware_detected = bool(nvidia)
        runtime_available = False
        name = (nvidia or {}).get("name")
        accelerator_memory = (nvidia or {}).get("memoryTotalMb")
        if nvidia and not torch_info["installed"]:
            reason = "检测到 NVIDIA GPU，但当前环境未安装 PyTorch。"
        elif nvidia and not torch_info["cudaRuntime"]:
            reason = "检测到 NVIDIA GPU，但当前 PyTorch 为 CPU 构建。"
        elif nvidia:
            reason = "检测到 NVIDIA GPU 和 CUDA 构建，但 CUDA Runtime 当前不可用。"
        else:
            reason = "当前主机未检测到可用 GPU。"

    return {
        "device": device,
        **memory,
        "accelerator": {
            "hardwareDetected": hardware_detected,
            "runtimeAvailable": runtime_available,
            "type": accelerator_type,
            "name": name,
            "memoryTotalMb": accelerator_memory,
            "driverVersion": (nvidia or {}).get("driverVersion"),
            "frameworkVersion": torch_info["version"],
            "frameworkBuild": torch_info["build"],
            "cudaRuntime": torch_info["cudaRuntime"],
            "reason": reason,
        },
    }


def get_device() -> str:
    return str(get_device_info()["device"])


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


def _read_windows_memory() -> dict[str, int | None]:
    if os.name != "nt":
        return {"total": None, "available": None}

    class MemoryStatusEx(ctypes.Structure):
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

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"total": None, "available": None}
    except Exception:
        return {"total": None, "available": None}
    return {
        "total": int(status.ullTotalPhys / 1024 / 1024),
        "available": int(status.ullAvailPhys / 1024 / 1024),
    }


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

    windows_memory = _read_windows_memory()
    if windows_memory["total"] is not None:
        total_mb = windows_memory["total"]
    if windows_memory["available"] is not None:
        available_mb = windows_memory["available"]

    if total_mb is None:
        total_mb = _read_macos_total_mb()
    if available_mb is None:
        available_mb = _read_macos_available_mb()
    return {"memoryTotalMb": total_mb, "memoryAvailableMb": available_mb}