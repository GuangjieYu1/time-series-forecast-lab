from datetime import datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CleaningConfig, CovariateConfig, FeatureConfig, ForecastRunRequest, HolidayConfig
from app.services.covariate_flow import active_model_covariate_columns, build_future_covariate_rows
from app.services.data_cleaner import detect_and_handle_outliers
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES, build_holiday_features
from app.services.series_builder import build_time_series


def request(**overrides):
    payload = {
        "uploadId": "test",
        "sheetName": "Sheet1",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["value"],
        "covariateColumns": [],
        "aggregation": {"enabled": False, "method": "sum"},
        "frequency": "auto",
        "horizon": 2,
        "testSize": 1,
        "selectedModels": ["naive"],
        "featureConfig": {"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "holidayFeatures": False, "covariates": True},
        "cleaningConfig": {"preset": "conservative"},
    }
    payload.update(overrides)
    return ForecastRunRequest.model_validate(payload)


def test_cleaning_presets_and_legacy_request_are_normalized():
    standard = CleaningConfig(preset="standard")
    strict = CleaningConfig(preset="strict")
    assert standard.missingValueStrategy == "time" and standard.interpolationLimit == 3
    assert strict.outlierStrategy == "hampel" and strict.interpolationLimit == 7
    legacy = ForecastRunRequest.model_validate({
        "uploadId": "x", "sheetName": "s", "dataMode": "aggregated", "timeColumn": "date",
        "targetColumns": ["value"], "horizon": 2, "testSize": 1, "selectedModels": ["naive"],
        "missingValueStrategy": "ffill",
    })
    assert legacy.cleaningConfig is not None
    assert legacy.cleaningConfig.preset == "custom"
    assert legacy.cleaningConfig.missingValueStrategy == "ffill"


def test_hampel_replaces_spike():
    frame = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=9), "value": [10, 10, 11, 10, 200, 10, 11, 10, 10]})
    cleaned, detected, adjusted = detect_and_handle_outliers(frame, "hampel", 1.5, 5, 3.0)
    assert detected == adjusted == 1
    assert cleaned.loc[4, "value"] < 20


def test_known_future_rows_are_retained_without_target_values():
    frame = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=7),
        "value": [10, 11, 12, 13, 14, None, None],
        "promo": [0, 0, 1, 0, 1, 1, 0],
    })
    result = build_time_series(frame, request(
        covariateColumns=["promo"],
        covariateConfigs=[{"column": "promo", "type": "known_future"}],
    ), "value")
    assert len(result.series.points) == 5
    assert result.series.futureCovariateRows == [{"promo": 1.0}, {"promo": 0.0}]


def test_static_covariates_respect_backtest_strategy_and_forecast_never_reads_test_values():
    market_config = CovariateConfig(column="market", type="static", backtestStrategy="use_test_values")
    region_config = CovariateConfig(column="region", type="static", backtestStrategy="historical_mean")
    assert active_model_covariate_columns(["market", "region"], [market_config, region_config]) == ["market", "region"]
    history_times = [datetime(2026, 1, 1) + timedelta(days=index) for index in range(6)]
    history_rows = [{"market": float(index), "region": float(10 + index)} for index in range(6)]
    forecast_rows = build_future_covariate_rows(
        covariate_columns=["market", "region"], history_rows=history_rows,
        observed_future_rows=[{"market": 999.0, "region": 999.0}, {"market": 998.0, "region": 998.0}],
        future_times=[history_times[-1] + timedelta(days=1), history_times[-1] + timedelta(days=2)],
        history_times=history_times, covariate_configs=[market_config, region_config], frequency="D", primary_model_id="naive", purpose="forecast",
    )
    backtest_rows = build_future_covariate_rows(
        covariate_columns=["market", "region"], history_rows=history_rows,
        observed_future_rows=[{"market": 999.0, "region": 999.0}, {"market": 998.0, "region": 998.0}],
        future_times=[history_times[-1] + timedelta(days=1), history_times[-1] + timedelta(days=2)],
        history_times=history_times, covariate_configs=[market_config, region_config], frequency="D", primary_model_id="naive", purpose="backtest",
    )
    assert forecast_rows == [{"market": 5.0, "region": 15.0}, {"market": 5.0, "region": 15.0}]
    assert backtest_rows == [{"market": 999.0, "region": 12.5}, {"market": 998.0, "region": 12.5}]


def test_holiday_features_cover_daily_and_monthly_periods():
    config = HolidayConfig(countryCode="CN", enabled=True)
    daily = build_holiday_features([datetime(2026, 1, 1), datetime(2026, 1, 2)], "D", config)
    monthly = build_holiday_features([datetime(2026, 1, 1)], "M", config)
    assert daily.names == HOLIDAY_FEATURE_NAMES
    assert daily.matrix.shape == (2, len(HOLIDAY_FEATURE_NAMES))
    assert monthly.matrix[0, HOLIDAY_FEATURE_NAMES.index("holiday_count")] >= 1
    assert any(marker.time == "2026-01-01" for marker in daily.markers)


def test_holiday_catalog_api():
    response = TestClient(app).get("/api/features/holiday-calendars")
    assert response.status_code == 200
    assert response.json()["defaultCountryCode"] == "CN"
    assert any(item["code"] == "CN" for item in response.json()["countries"])
