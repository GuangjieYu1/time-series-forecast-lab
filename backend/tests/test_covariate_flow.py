from __future__ import annotations

from datetime import datetime

from app.services.covariate_flow import build_future_covariate_rows, covariate_strategy_warnings, describe_covariates


def test_describe_covariates_classifies_known_future_and_static():
    descriptors = describe_covariates(["holiday", "weekday", "temperature", "flight_count"])

    assert [item["type"] for item in descriptors] == ["known_future", "known_future", "static", "static"]
    assert descriptors[0]["forecastStrategy"] == "calendar"
    assert descriptors[1]["backtestStrategy"] == "use_test_timeline"
    assert descriptors[2]["forecastStrategy"] == "repeat_last_known"
    assert descriptors[3]["backtestStrategy"] == "repeat_last_known"

    warnings = covariate_strategy_warnings(["holiday", "temperature"])
    assert any("Static Covariate" in warning for warning in warnings)
    assert any("Known Future Covariate" in warning for warning in warnings)


def test_build_future_covariate_rows_generates_known_future_and_repeats_static():
    rows = build_future_covariate_rows(
        covariate_columns=["temperature", "weekday", "holiday"],
        history_rows=[{"temperature": 25.0, "weekday": 4.0, "holiday": 0.0}],
        observed_future_rows=[
            {"temperature": 999.0, "weekday": 9.0, "holiday": 9.0},
            {"temperature": 998.0, "weekday": 9.0, "holiday": 9.0},
        ],
        future_times=[
            datetime(2026, 1, 5, 0, 0),  # Monday
            datetime(2026, 1, 10, 0, 0),  # Saturday
        ],
    )

    assert rows == [
        {"temperature": 25.0, "weekday": 0.0, "holiday": 0.0},
        {"temperature": 25.0, "weekday": 5.0, "holiday": 1.0},
    ]
