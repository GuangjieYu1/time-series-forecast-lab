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
        "| case | category | format | rows | cols | health | best_mae | upload | run | seconds | warnings |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['name']} | {case['category']} | {case.get('fileFormat', '-')} | {case.get('rowCount', '-')} | {case.get('columnCount', '-')} | {case.get('dataHealthScore', '-')} | {case.get('bestMae', '-')} | {case['uploadStatus']} | {case['runStatus']} | {case['seconds']} | {case['warningCount']} |"
        )
    for case in summary["cases"]:
        lines.extend(
            [
                "",
                f"## {case['name']}",
                "",
                f"- category: `{case['category']}`",
                f"- file format: `{case.get('fileFormat', '-')}`",
                f"- target columns: `{', '.join(case.get('targetColumns', [])) or '-'}`",
                f"- covariate columns: `{', '.join(case.get('covariateColumns', [])) or '-'}`",
                f"- selected models: `{', '.join(case.get('selectedModels', [])) or '-'}`",
                f"- data health score: `{case.get('dataHealthScore', '-')}`",
                f"- best MAE: `{case.get('bestMae', '-')}`",
                f"- warning count: `{case['warningCount']}`",
            ]
        )
        if case.get("error"):
            lines.extend(["", "### run error", "", "```text", str(case["error"]), "```"])
        model_results = case.get("modelResults", [])
        if model_results:
            lines.extend(
                [
                    "",
                    "### model results",
                    "",
                    "| model | status | MAE | RMSE | WAPE | warnings | error |",
                    "| --- | --- | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for model in model_results:
                metrics = model.get("metrics") or {}
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(model.get("modelName") or model.get("modelId") or "-"),
                            str(model.get("status") or "-"),
                            str(metrics.get("mae", "-")),
                            str(metrics.get("rmse", "-")),
                            str(metrics.get("wape", "-")),
                            str(len(model.get("warnings", []))),
                            str(model.get("error") or "-"),
                        ]
                    )
                    + " |"
                )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
