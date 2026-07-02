from __future__ import annotations

from pathlib import Path


def benchmark_root(backend_root: Path) -> Path:
    return backend_root / "benchmarks"


def reports_dir(backend_root: Path) -> Path:
    return benchmark_root(backend_root) / "reports"


def legacy_output_dir(backend_root: Path) -> Path:
    return benchmark_root(backend_root) / "output"
