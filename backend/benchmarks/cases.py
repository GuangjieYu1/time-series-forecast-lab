from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    category: str
    path: Path
    content_type: str
    request: dict


def build_cases(root: Path) -> list[BenchmarkCase]:
    fixture_root = root / "benchmarks" / "fixtures"
    return [
        BenchmarkCase(
            name="daily_clean",
            category="clean",
            path=fixture_root / "clean" / "daily_clean.csv",
            content_type="text/csv",
            request={
                "sheetName": "CSV",
                "dataMode": "aggregated",
                "timeColumn": "date",
                "targetColumns": ["value"],
                "aggregation": {"enabled": False, "method": "sum"},
                "frequency": "auto",
                "horizon": 14,
                "testSize": 14,
                "selectedModels": ["naive", "moving_average", "ets"],
                "modelParameters": {},
                "missingValueStrategy": "drop",
                "fillMissingTimeSteps": True,
                "duplicateTimeStrategy": "mean",
                "outlierStrategy": "none",
                "outlierIqrMultiplier": 1.5,
                "trimStrings": True,
            },
        ),
        BenchmarkCase(
            name="daily_dirty",
            category="dirty",
            path=fixture_root / "dirty" / "daily_dirty.csv",
            content_type="text/csv",
            request={
                "sheetName": "CSV",
                "dataMode": "aggregated",
                "timeColumn": "date",
                "targetColumns": ["value"],
                "aggregation": {"enabled": False, "method": "sum"},
                "frequency": "auto",
                "horizon": 10,
                "testSize": 10,
                "selectedModels": ["naive", "moving_average", "arima"],
                "modelParameters": {},
                "missingValueStrategy": "interpolate",
                "fillMissingTimeSteps": True,
                "duplicateTimeStrategy": "mean",
                "outlierStrategy": "clip_iqr",
                "outlierIqrMultiplier": 1.5,
                "trimStrings": True,
            },
        ),
        BenchmarkCase(
            name="daily_edge_short",
            category="edge",
            path=fixture_root / "edge" / "daily_edge_short.csv",
            content_type="text/csv",
            request={
                "sheetName": "CSV",
                "dataMode": "aggregated",
                "timeColumn": "date",
                "targetColumns": ["value"],
                "aggregation": {"enabled": False, "method": "sum"},
                "frequency": "auto",
                "horizon": 3,
                "testSize": 3,
                "selectedModels": ["naive", "moving_average"],
                "modelParameters": {},
                "missingValueStrategy": "drop",
                "fillMissingTimeSteps": True,
                "duplicateTimeStrategy": "mean",
                "outlierStrategy": "none",
                "outlierIqrMultiplier": 1.5,
                "trimStrings": True,
            },
        ),
        BenchmarkCase(
            name="large_hourly",
            category="large",
            path=fixture_root / "large" / "large_hourly.csv",
            content_type="text/csv",
            request={
                "sheetName": "CSV",
                "dataMode": "aggregated",
                "timeColumn": "date",
                "targetColumns": ["value"],
                "aggregation": {"enabled": False, "method": "sum"},
                "frequency": "auto",
                "horizon": 24,
                "testSize": 48,
                "selectedModels": ["naive", "moving_average"],
                "modelParameters": {},
                "missingValueStrategy": "ffill",
                "fillMissingTimeSteps": True,
                "duplicateTimeStrategy": "mean",
                "outlierStrategy": "none",
                "outlierIqrMultiplier": 1.5,
                "trimStrings": True,
            },
        ),
        BenchmarkCase(
            name="etth1_smoke",
            category="clean",
            path=root / "tests" / "fixtures" / "professional" / "ETTh1.csv",
            content_type="text/csv",
            request={
                "sheetName": "CSV",
                "dataMode": "aggregated",
                "timeColumn": "date",
                "targetColumns": ["OT"],
                "aggregation": {"enabled": False, "method": "sum"},
                "frequency": "auto",
                "horizon": 24,
                "testSize": 24,
                "selectedModels": ["naive", "xgboost"],
                "modelParameters": {"xgboost": {"nEstimators": 40, "maxDepth": 2, "learningRate": 0.08}},
                "missingValueStrategy": "drop",
                "fillMissingTimeSteps": True,
                "duplicateTimeStrategy": "mean",
                "outlierStrategy": "none",
                "outlierIqrMultiplier": 1.5,
                "trimStrings": True,
            },
        ),
    ]
