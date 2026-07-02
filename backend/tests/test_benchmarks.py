from __future__ import annotations

import json

from benchmarks.benchmark_report import write_summary


def test_benchmark_report_writes_reports_and_legacy_output(tmp_path):
    backend_root = tmp_path
    summary = {
        "profile": "fast",
        "generatedAt": "2026-07-02T00:00:00+00:00",
        "seconds": 1.2,
        "totalCases": 1,
        "successfulRuns": 1,
        "failedRuns": 0,
        "cases": [
            {
                "name": "daily_clean",
                "category": "clean",
                "fileFormat": "csv",
                "rowCount": 120,
                "columnCount": 2,
                "targetColumns": ["value"],
                "covariateColumns": [],
                "selectedModels": ["naive"],
                "uploadStatus": "200",
                "runStatus": "200",
                "seconds": 0.8,
                "memoryMb": 12.5,
                "warningCount": 1,
                "bestMae": 0.42,
                "dataHealthScore": 96,
                "modelStatuses": {"naive": "success"},
                "modelResults": [
                    {
                        "modelId": "naive",
                        "modelName": "Naive",
                        "status": "success",
                        "warnings": ["ok"],
                        "error": None,
                        "metrics": {"mae": 0.42, "rmse": 0.5, "wape": 0.08},
                    }
                ],
                "experimentId": None,
                "error": None,
            }
        ],
    }

    json_path, md_path = write_summary(backend_root, summary)

    assert json_path == backend_root / "benchmarks" / "reports" / "benchmark_summary.json"
    assert md_path == backend_root / "benchmarks" / "reports" / "benchmark_summary.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["cases"][0]["dataHealthScore"] == 96
    assert (backend_root / "benchmarks" / "output" / "benchmark_summary.json").exists()
    assert "model results" in md_path.read_text(encoding="utf-8")
