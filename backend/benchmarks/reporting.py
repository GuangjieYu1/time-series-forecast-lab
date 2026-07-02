from __future__ import annotations

import json
from pathlib import Path


def write_summary(output_dir: Path, summary: dict) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_summary.json"
    md_path = output_dir / "benchmark_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Benchmark Summary",
        "",
        f"- profile: `{summary['profile']}`",
        f"- total cases: `{summary['totalCases']}`",
        f"- successful API runs: `{summary['successfulRuns']}`",
        f"- failed API runs: `{summary['failedRuns']}`",
        f"- generated at: `{summary['generatedAt']}`",
        "",
        "| case | category | upload | run | seconds | memory_mb | warnings |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['name']} | {case['category']} | {case['uploadStatus']} | {case['runStatus']} | {case['seconds']} | {case['memoryMb']} | {case['warningCount']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
