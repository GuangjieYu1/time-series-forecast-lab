from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    category: str
    path: Path
    content_type: str
    request: dict
    suite: str = "stability"
    thresholds: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)


def _base_request(sheet_name: str, time_column: str, target_column: str) -> dict:
    return {
        "sheetName": sheet_name,
        "dataMode": "aggregated",
        "timeColumn": time_column,
        "targetColumns": [target_column],
        "aggregation": {"enabled": False, "method": "sum"},
        "frequency": "auto",
        "horizon": 7,
        "testSize": 7,
        "selectedModels": ["naive", "moving_average"],
        "modelParameters": {},
        "missingValueStrategy": "drop",
        "fillMissingTimeSteps": True,
        "duplicateTimeStrategy": "mean",
        "outlierStrategy": "none",
        "outlierIqrMultiplier": 1.5,
        "trimStrings": True,
    }


def build_cases(root: Path) -> list[BenchmarkCase]:
    fixture_root = root / "benchmarks" / "fixtures"
    return [
        BenchmarkCase("daily_clean", "clean", fixture_root / "clean" / "daily_clean.csv", "text/csv", {**_base_request("CSV", "date", "value"), "horizon": 14, "testSize": 14, "selectedModels": ["naive", "moving_average", "ets"]}),
        BenchmarkCase("daily_dirty", "dirty", fixture_root / "dirty" / "daily_dirty.csv", "text/csv", {**_base_request("CSV", "date", "value"), "horizon": 10, "testSize": 10, "selectedModels": ["naive", "moving_average", "arima"], "missingValueStrategy": "interpolate", "outlierStrategy": "clip_iqr"}),
        BenchmarkCase("daily_edge_short", "edge", fixture_root / "edge" / "daily_edge_short.csv", "text/csv", {**_base_request("CSV", "date", "value"), "horizon": 3, "testSize": 3}),
        BenchmarkCase("large_hourly", "large", fixture_root / "large" / "large_hourly.csv", "text/csv", {**_base_request("CSV", "date", "value"), "horizon": 24, "testSize": 48, "missingValueStrategy": "ffill"}),
        BenchmarkCase("etth1_smoke", "clean", root / "tests" / "fixtures" / "professional" / "ETTh1.csv", "text/csv", {**_base_request("CSV", "date", "OT"), "horizon": 24, "testSize": 24, "selectedModels": ["naive", "xgboost"], "modelParameters": {"xgboost": {"nEstimators": 40, "maxDepth": 2, "learningRate": 0.08}}}),
        BenchmarkCase(
            "raw_detail_sum", "aggregation", fixture_root / "aggregation" / "raw_detail.csv", "text/csv",
            {**_base_request("CSV", "flight_date", "passenger_count"), "dataMode": "raw", "aggregation": {"enabled": True, "method": "sum"}, "horizon": 2, "testSize": 2, "selectedModels": ["naive"]},
            suite="aggregation_correctness",
            expected={"method": "sum", "series": [["2024-01-01T00:00:00", 30.0], ["2024-01-02T00:00:00", 12.0], ["2024-01-03T00:00:00", 30.0], ["2024-01-04T00:00:00", 18.0], ["2024-01-05T00:00:00", 20.0], ["2024-01-06T00:00:00", 28.0]]},
        ),
        BenchmarkCase(
            "raw_detail_mean", "aggregation", fixture_root / "aggregation" / "raw_detail.csv", "text/csv",
            {**_base_request("CSV", "flight_date", "passenger_count"), "dataMode": "raw", "aggregation": {"enabled": True, "method": "mean"}, "horizon": 2, "testSize": 2, "selectedModels": ["naive"]},
            suite="aggregation_correctness",
            thresholds={"tolerance": 1e-9},
            expected={"method": "mean", "series": [["2024-01-01T00:00:00", 15.0], ["2024-01-02T00:00:00", 12.0], ["2024-01-03T00:00:00", 30.0], ["2024-01-04T00:00:00", 9.0], ["2024-01-05T00:00:00", 20.0], ["2024-01-06T00:00:00", 14.0]]},
        ),
        BenchmarkCase(
            "raw_detail_count", "aggregation", fixture_root / "aggregation" / "raw_detail.csv", "text/csv",
            {**_base_request("CSV", "flight_date", "passenger_count"), "dataMode": "raw", "aggregation": {"enabled": True, "method": "count"}, "horizon": 2, "testSize": 2, "selectedModels": ["naive"]},
            suite="aggregation_correctness",
            expected={"method": "count", "series": [["2024-01-01T00:00:00", 2.0], ["2024-01-02T00:00:00", 2.0], ["2024-01-03T00:00:00", 1.0], ["2024-01-04T00:00:00", 2.0], ["2024-01-05T00:00:00", 1.0], ["2024-01-06T00:00:00", 2.0]]},
        ),
        BenchmarkCase("repro_daily_clean", "reproducibility", fixture_root / "clean" / "daily_clean.csv", "text/csv", {**_base_request("CSV", "date", "value"), "horizon": 7, "testSize": 7, "selectedModels": ["naive", "moving_average"], "randomSeed": 42}, suite="reproducibility", thresholds={"metricTolerance": 1e-8}),
    ]
