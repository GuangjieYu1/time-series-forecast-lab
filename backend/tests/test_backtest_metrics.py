from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

import app.services.backtest_runner as backtest_runner
from app.schemas import Diagnostics
from app.services.backtest_runner import run_holdout_backtest
from app.services.metrics import calculate_metrics
from app.services.series_builder import TimeSeriesData, TimeSeriesPoint


def make_series(values: list[float]) -> TimeSeriesData:
    return TimeSeriesData(
        targetColumn="y",
        frequency="D",
        points=[TimeSeriesPoint(time=datetime(2026, 1, 1) + timedelta(days=index), value=value) for index, value in enumerate(values)],
        diagnostics=Diagnostics(
            originalRowCount=len(values),
            validRowCount=len(values),
            droppedRowCount=0,
            duplicateTimeCount=0,
            missingTimeCount=0,
            timeStart=None,
            timeEnd=None,
        ),
    )


def test_holdout_split_boundaries(monkeypatch):
    observed: dict[str, list[float]] = {}

    class RecordingModel:
        def fit(self, times, values, frequency):
            observed["train_values"] = values
            observed["train_times"] = times

        def predict(self, horizon):
            from app.models.base import ForecastOutput

            return ForecastOutput(predictions=[0] * horizon)

    monkeypatch.setattr(backtest_runner, "create_model", lambda model_id, parameters=None: RecordingModel())
    result = run_holdout_backtest(make_series([float(i) for i in range(20)]), ["naive"], horizon=5, test_size=5)
    assert observed["train_values"] == [float(i) for i in range(15)]
    assert result.backtest.actual[0].value == 15
    assert result.backtest.actual[-1].value == 19


def test_residual_definition_actual_minus_predicted(monkeypatch):
    class FixedModel:
        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            from app.models.base import ForecastOutput

            return ForecastOutput(predictions=[100, 100])

    monkeypatch.setattr(backtest_runner, "create_model", lambda model_id, parameters=None: FixedModel())
    result = run_holdout_backtest(make_series([1, 2, 120, 80]), ["naive"], horizon=2, test_size=2)
    residuals = [point.residual for point in result.backtest.predictions["naive"]]
    assert residuals == [20, -20]


def test_metrics_are_calculated_correctly():
    metrics, warnings = calculate_metrics(actual=[120, 80], predicted=[100, 100])
    assert metrics.mse == 400
    assert metrics.mae == 20
    assert metrics.rmse == 20
    assert metrics.wape == pytest.approx(0.2)
    assert warnings == []


def test_wape_zero_denominator_returns_null_warning():
    metrics, warnings = calculate_metrics(actual=[0, 0], predicted=[1, -1])
    assert metrics.wape is None
    assert warnings


def test_nan_predictions_are_failed(monkeypatch):
    class NanModel:
        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            from app.models.base import ForecastOutput

            return ForecastOutput(predictions=[math.nan] * horizon)

    monkeypatch.setattr(backtest_runner, "create_model", lambda model_id, parameters=None: NanModel())
    result = run_holdout_backtest(make_series([1, 2, 3, 4]), ["naive"], horizon=2, test_size=2)
    assert result.rankedModels[0].status == "failed"
    assert "NaN" in (result.rankedModels[0].error or "")


def test_backtest_reports_real_model_stages(monkeypatch):
    class FixedModel:
        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            from app.models.base import ForecastOutput

            return ForecastOutput(predictions=[10.0] * horizon)

    monkeypatch.setattr(backtest_runner, "create_model", lambda model_id, parameters=None: FixedModel())
    events = []
    run_holdout_backtest(
        make_series([float(index) for index in range(40)]),
        ["naive"],
        horizon=5,
        test_size=5,
        progress_callback=events.append,
    )

    assert [event.stage for event in events] == ["fitting", "predicting", "scoring", "success"]
    assert events[-1].fitSeconds >= 0
    assert events[-1].predictSeconds >= 0


def test_model_parameters_are_passed_to_factory(monkeypatch):
    observed = {}

    class FixedModel:
        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            from app.models.base import ForecastOutput

            return ForecastOutput(predictions=[10.0] * horizon)

    def factory(model_id, parameters=None):
        observed[model_id] = parameters
        return FixedModel()

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    run_holdout_backtest(
        make_series([float(index) for index in range(40)]),
        ["moving_average"],
        horizon=5,
        test_size=5,
        model_parameters={"moving_average": {"window": 14}},
    )

    assert observed["moving_average"] == {"window": 14}
