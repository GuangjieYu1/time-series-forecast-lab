from __future__ import annotations

from pathlib import Path

from benchmarks.benchmark_config import legacy_output_dir, reports_dir
from benchmarks.reporting import write_summary as write_summary_file


def write_summary(backend_root: Path, summary: dict) -> tuple[Path, Path]:
    json_path, md_path = write_summary_file(reports_dir(backend_root), summary)
    write_summary_file(legacy_output_dir(backend_root), summary)
    return json_path, md_path
