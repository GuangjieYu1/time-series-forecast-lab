from __future__ import annotations

import json
from pathlib import Path


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def write_summary(output_dir: Path, summary: dict) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_summary.json"
    md_path = output_dir / "benchmark_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Benchmark Summary",
        "",
        f"- schema: `{summary.get('schemaVersion', '0.5')}`",
        f"- suite: `{summary.get('suite', 'all')}`",
        f"- profile: `{summary['profile']}`",
        f"- agent mode: `{summary.get('agentMode', 'offline')}`",
        f"- total cases: `{summary['totalCases']}`",
        f"- successful API runs: `{summary['successfulRuns']}`",
        f"- failed API runs: `{summary['failedRuns']}`",
        f"- failed assertions: `{summary.get('failedAssertions', 0)}`",
        f"- warning assertions: `{summary.get('warningAssertions', 0)}`",
        f"- generated at: `{summary['generatedAt']}`",
        "",
        "| case | suite | category | passed | rows | best_mae | run | seconds | assertions |",
        "| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(f"| {case['name']} | {case.get('suite', '-')} | {case['category']} | {case.get('passed', True)} | {_fmt(case.get('rowCount'))} | {_fmt(case.get('bestMae'))} | {case.get('runStatus', '-')} | {_fmt(case.get('seconds'))} | {len(case.get('assertions', []))} |")
    for case in summary["cases"]:
        lines.extend(["", f"## {case['name']}", "", f"- suite: `{case.get('suite', '-')}`", f"- category: `{case['category']}`", f"- passed: `{case.get('passed', True)}`", f"- warning count: `{case.get('warningCount', 0)}`"])
        if case.get("error"):
            lines.extend(["", "### run error", "", "```text", str(case["error"]), "```"])
        assertions = case.get("assertions", [])
        if assertions:
            lines.extend(["", "### assertions", "", "| assertion | status | message |", "| --- | --- | --- |"])
            for assertion in assertions:
                lines.append(f"| {assertion.get('name')} | {assertion.get('status')} | {str(assertion.get('message', '')).replace('|', '/')} |")
        model_results = case.get("modelResults", [])
        if model_results:
            lines.extend(["", "### model results", "", "| model | status | MAE | RMSE | WAPE | warnings | error |", "| --- | --- | ---: | ---: | ---: | ---: | --- |"])
            for model in model_results:
                metrics = model.get("metrics") or {}
                lines.append("| " + " | ".join([str(model.get("modelName") or model.get("modelId") or "-"), str(model.get("status") or "-"), _fmt(metrics.get("mae")), _fmt(metrics.get("rmse")), _fmt(metrics.get("wape")), str(len(model.get("warnings", []))), str(model.get("error") or "-")]) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
