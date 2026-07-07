from __future__ import annotations

from pathlib import Path

from benchmarks.benchmark_runner import _hash_json
from benchmarks.generators.generate_fixtures import ensure_benchmark_fixtures
from benchmarks.schemas import BenchmarkSummary


def test_benchmark_v05_schema_accepts_new_result_shapes(tmp_path: Path):
    summary = BenchmarkSummary.model_validate(
        {
            "profile": "fast",
            "suite": "agent",
            "agentMode": "offline",
            "generatedAt": "2026-07-07T00:00:00+00:00",
            "seconds": 1.0,
            "totalCases": 1,
            "successfulRuns": 1,
            "failedRuns": 0,
            "successRate": 1.0,
            "failureRate": 0.0,
            "cases": [
                {
                    "name": "workbench_agent_golden_routes",
                    "suite": "agent_routing",
                    "category": "agent",
                    "seconds": 0.1,
                    "memoryMb": 0.0,
                    "warningCount": 0,
                    "agentRoutingResult": {"routeAccuracy": 1.0, "schemaValidity": 1.0, "leakageWarningRecall": 1.0, "unsupportedPromiseCount": 0},
                }
            ],
        }
    )
    assert summary.schemaVersion == "0.5"
    assert summary.cases[0].agentRoutingResult is not None


def test_benchmark_fixture_generator_creates_v05_fixtures(tmp_path: Path):
    fixture_root = ensure_benchmark_fixtures(tmp_path)
    assert (fixture_root / "aggregation" / "raw_detail.csv").exists()
    assert (fixture_root / "feature_lift" / "positive_covariate.csv").exists()
    assert _hash_json([["2024-01-01", 1.0]]) == _hash_json([["2024-01-01", 1.0]])
