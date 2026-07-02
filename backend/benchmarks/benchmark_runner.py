from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from benchmarks.cases import build_cases
from benchmarks.generators.generate_fixtures import ensure_benchmark_fixtures
from benchmarks.metrics import elapsed_seconds, max_rss_mb, now
from benchmarks.reporting import write_summary


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
        model_statuses: dict[str, str] = {}
        error: str | None = None
        experiment_id: str | None = None
        try:
            with case.path.open("rb") as handle:
                upload_response = client.post("/api/upload/preview", files={"file": (case.path.name, handle, case.content_type)})
            upload_status = str(upload_response.status_code)
            if upload_response.status_code != 200:
                error = upload_response.text
                raise RuntimeError(error)

            upload_body = upload_response.json()
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
                model_statuses = {model["modelId"]: model["status"] for model in body.get("rankedModels", [])}
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
                "uploadStatus": upload_status,
                "runStatus": run_status,
                "seconds": elapsed_seconds(case_started),
                "memoryMb": max(0.0, round(max_rss_mb() - memory_before, 2)),
                "warningCount": warning_count,
                "modelStatuses": model_statuses,
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
    output_dir = backend_root / "benchmarks" / "output"
    json_path, md_path = write_summary(output_dir, summary)
    print(f"benchmark summary written to {json_path}")
    print(f"benchmark report written to {md_path}")


if __name__ == "__main__":
    main()
