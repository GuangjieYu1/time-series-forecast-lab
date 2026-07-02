from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from benchmarks.benchmark_cases import build_cases
from benchmarks.benchmark_metrics import elapsed_seconds, max_rss_mb, now
from benchmarks.benchmark_report import write_summary
from benchmarks.generators.generate_fixtures import ensure_benchmark_fixtures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run trustworthy forecast lab benchmarks.")
    parser.add_argument("--profile", choices=["fast", "balanced", "accurate"], default="balanced")
    parser.add_argument("--dirty-only", action="store_true")
    parser.add_argument("--large-only", action="store_true")
    parser.add_argument("--case")
    return parser.parse_args()


def _selected_cases(root: Path, args: argparse.Namespace):
    cases = build_cases(root)
    if args.case:
        cases = [case for case in cases if case.name == args.case]
    if args.dirty_only:
        cases = [case for case in cases if case.category == "dirty"]
    if args.large_only:
        cases = [case for case in cases if case.category == "large"]
    return cases


def main() -> None:
    args = _parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    ensure_benchmark_fixtures(backend_root)
    client = TestClient(app)
    cases = _selected_cases(backend_root, args)
    started = now()
    results: list[dict] = []

    for case in cases:
        case_started = now()
        memory_before = max_rss_mb()
        upload_status = "failed"
        run_status = "skipped"
        warning_count = 0
        best_mae = None
        data_health_score = None
        model_statuses: dict[str, str] = {}
        model_results: list[dict] = []
        error: str | None = None
        experiment_id: str | None = None
        row_count = None
        column_count = None
        selected_sheet: dict | None = None
        try:
            with case.path.open("rb") as handle:
                upload_response = client.post("/api/upload/preview", files={"file": (case.path.name, handle, case.content_type)})
            upload_status = str(upload_response.status_code)
            if upload_response.status_code != 200:
                error = upload_response.text
                raise RuntimeError(error)

            upload_body = upload_response.json()
            selected_sheet = next((sheet for sheet in upload_body.get("sheets", []) if sheet.get("sheetName") == case.request["sheetName"]), None)
            if selected_sheet is None:
                sheets = upload_body.get("sheets", [])
                selected_sheet = sheets[0] if sheets else None
            if isinstance(selected_sheet, dict):
                row_count = selected_sheet.get("rowCountApprox")
                column_count = len(selected_sheet.get("columns", []))
            run_request = {
                "runId": f"bench_{case.name}",
                "uploadId": upload_body["uploadId"],
                "runProfile": args.profile,
                "parameterStrategy": "auto" if args.profile != "fast" else "default",
                "randomSeed": 42,
                **case.request,
            }
            run_response = client.post("/api/forecast/run", json=run_request)
            run_status = str(run_response.status_code)
            if run_response.status_code == 200:
                body = run_response.json()
                experiment_id = body["experimentId"]
                warning_count = len(body["diagnostics"].get("warnings", [])) + sum(
                    len(model.get("warnings", [])) for model in body.get("rankedModels", [])
                )
                best_mae = next(
                    (
                        model["metrics"]["mae"]
                        for model in body.get("rankedModels", [])
                        if model.get("status") == "success" and isinstance(model.get("metrics"), dict) and model["metrics"].get("mae") is not None
                    ),
                    None,
                )
                data_health_score = (body.get("dataHealth") or {}).get("score")
                model_statuses = {model["modelId"]: model["status"] for model in body.get("rankedModels", [])}
                model_results = [
                    {
                        "modelId": model.get("modelId"),
                        "modelName": model.get("modelName"),
                        "status": model.get("status"),
                        "warnings": model.get("warnings", []),
                        "error": model.get("error"),
                        "metrics": model.get("metrics"),
                    }
                    for model in body.get("rankedModels", [])
                ]
                client.delete(f"/api/experiments/{experiment_id}")
            else:
                error = run_response.text
        except Exception as exc:
            if error is None:
                error = str(exc)
        results.append(
            {
                "name": case.name,
                "category": case.category,
                "fileFormat": case.path.suffix.lstrip("."),
                "rowCount": row_count,
                "columnCount": column_count,
                "targetColumns": case.request.get("targetColumns", []),
                "covariateColumns": case.request.get("covariateColumns", []),
                "selectedModels": case.request.get("selectedModels", []),
                "uploadStatus": upload_status,
                "runStatus": run_status,
                "seconds": elapsed_seconds(case_started),
                "memoryMb": max(0.0, round(max_rss_mb() - memory_before, 2)),
                "warningCount": warning_count,
                "bestMae": best_mae,
                "dataHealthScore": data_health_score,
                "modelStatuses": model_statuses,
                "modelResults": model_results,
                "experimentId": experiment_id,
                "error": error,
            }
        )

    summary = {
        "profile": args.profile,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seconds": elapsed_seconds(started),
        "totalCases": len(results),
        "successfulRuns": sum(1 for result in results if result["runStatus"] == "200"),
        "failedRuns": sum(1 for result in results if result["runStatus"] != "200"),
        "cases": results,
    }
    json_path, md_path = write_summary(backend_root, summary)
    print(f"benchmark summary written to {json_path}")
    print(f"benchmark report written to {md_path}")


if __name__ == "__main__":
    main()
