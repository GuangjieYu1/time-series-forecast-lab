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


def test_basic_cleaning_trims_numeric_text_and_interpolates_missing_target():
    df = pd.DataFrame(
        {
            "date": [" 2026-06-01 ", "2026-06-02", "2026-06-03", "bad-date"],
            "passenger_count": [" 1,200 ", None, "1,600", "900"],
        }
    )
    result = build_time_series(
        df,
        request(missingValueStrategy="interpolate"),
        "passenger_count",
    )
    assert [point.value for point in result.series.points] == [1200, 1400, 1600]
    assert result.series.diagnostics.invalidTimeCount == 1
    assert result.series.diagnostics.inputMissingTargetCount == 1
    assert result.series.diagnostics.filledValueCount == 1
    assert result.series.diagnostics.droppedRowCount == 1


def test_duplicate_strategy_last_is_applied():
    df = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-03"],
            "passenger_count": [100, 120, 130, 140],
        }
    )
    result = build_time_series(
        df,
        request(duplicateTimeStrategy="last", fillMissingTimeSteps=False),
        "passenger_count",
    )
    assert [point.value for point in result.series.points] == [120, 130, 140]


def test_iqr_outliers_are_detected_and_optionally_clipped():
    values = [10, 11, 9, 10, 12, 11, 10, 9, 11, 10, 1000]
    dates = pd.date_range("2026-06-01", periods=len(values), freq="D")
    df = pd.DataFrame({"date": dates, "passenger_count": values})

    detected = build_time_series(df, request(outlierStrategy="none"), "passenger_count")
    clipped = build_time_series(df, request(outlierStrategy="clip_iqr"), "passenger_count")

    assert detected.series.diagnostics.outlierCount == 1
    assert detected.series.points[-1].value == 1000
    assert clipped.series.diagnostics.outlierAdjustedCount == 1
    assert clipped.series.points[-1].value < 1000


def test_missing_time_steps_can_be_interpolated():
    df = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-03", "2026-06-04"],
            "passenger_count": [100, 140, 160],
        }
    )
    result = build_time_series(
        df,
        request(missingValueStrategy="interpolate"),
        "passenger_count",
    )
    assert [point.value for point in result.series.points] == [100, 120, 140, 160]
    assert result.series.diagnostics.missingTimeCount == 1
    assert result.series.diagnostics.filledValueCount == 1


def test_covariates_are_aligned_and_missing_values_are_filled():
    df = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"],
            "passenger_count": [100, 120, 140, 160],
            "temperature": [26.0, None, 30.0, 31.0],
            "promo_flag": [1, 0, 1, 1],
        }
    )
    result = build_time_series(
        df,
        request(
            covariateColumns=["temperature", "promo_flag"],
            missingValueStrategy="ffill",
        ),
        "passenger_count",
    )

    assert result.series.covariateColumns == ["temperature", "promo_flag"]
    assert len(result.series.covariateRows) == len(result.series.points)
    assert result.series.covariateRows[0]["temperature"] == 26.0
    assert result.series.covariateRows[1]["temperature"] == 26.0
    assert result.series.covariateRows[2]["promo_flag"] == 1.0
    assert result.data_profile["featureConfig"]["covariates"] is True
