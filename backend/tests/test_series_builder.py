from __future__ import annotations

import pandas as pd
import pytest

from app.core.errors import AppError
from app.schemas import AggregationConfig, ForecastRunRequest
from app.services.series_builder import build_time_series


def request(**overrides) -> ForecastRunRequest:
    data = {
        "uploadId": "tmp_test",
        "sheetName": "Sheet1",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["passenger_count"],
        "aggregation": AggregationConfig(enabled=False, method="sum"),
        "frequency": "auto",
        "horizon": 2,
        "testSize": 2,
        "selectedModels": ["naive"],
        "missingValueStrategy": "drop",
        "fillMissingTimeSteps": True,
    }
    data.update(overrides)
    return ForecastRunRequest(**data)


def test_aggregated_series_preserves_single_rows():
    df = pd.DataFrame({"date": ["2026-06-01", "2026-06-02", "2026-06-03"], "passenger_count": [10, 20, 30]})
    result = build_time_series(df, request(), "passenger_count")
    assert [point.value for point in result.series.points] == [10, 20, 30]
    assert result.series.frequency == "D"


def test_raw_detail_sum_aggregation():
    df = pd.DataFrame(
        {
            "flight_date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02", "2026-06-03"],
            "passenger_count": [100, 120, 80, 90, 50],
        }
    )
    result = build_time_series(
        df,
        request(dataMode="raw", timeColumn="flight_date", aggregation=AggregationConfig(enabled=True, method="sum")),
        "passenger_count",
    )
    assert [point.value for point in result.series.points] == [220, 170, 50]


def test_duplicate_aggregated_dates_are_warned_and_averaged():
    df = pd.DataFrame({"date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-03"], "passenger_count": [100, 120, 130, 140]})
    result = build_time_series(df, request(fillMissingTimeSteps=False), "passenger_count")
    assert [point.value for point in result.series.points] == [110, 130, 140]
    assert result.series.diagnostics.duplicateTimeCount == 1
    assert any("Duplicate timestamps" in warning for warning in result.series.diagnostics.warnings)


def test_missing_time_steps_drop_strategy():
    df = pd.DataFrame({"date": ["2026-06-01", "2026-06-03", "2026-06-04"], "passenger_count": [100, 130, 140]})
    result = build_time_series(df, request(missingValueStrategy="drop"), "passenger_count")
    assert result.series.diagnostics.missingTimeCount == 1
    assert [point.time.day for point in result.series.points] == [1, 3, 4]


def test_frequency_too_fine_is_rejected():
    df = pd.DataFrame({"date": ["2026-06-01", "2026-06-02", "2026-06-03"], "passenger_count": [10, 20, 30]})
    with pytest.raises(AppError) as exc:
        build_time_series(df, request(frequency="H"), "passenger_count")
    assert exc.value.code == "FREQUENCY_TOO_FINE"
