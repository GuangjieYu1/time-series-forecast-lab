from __future__ import annotations

from datetime import datetime, timedelta

import app.services.backtest_runner as backtest_runner
from app.schemas import Diagnostics
from app.services.backtest_runner import run_holdout_backtest
from app.services.series_builder import TimeSeriesData, TimeSeriesPoint


def series() -> TimeSeriesData:
    return TimeSeriesData(
        targetColumn="y",
        frequency="D",
        points=[TimeSeriesPoint(time=datetime(2026, 1, 1) + timedelta(days=index), value=float(index + 1)) for index in range(40)],
        diagnostics=Diagnostics(
            originalRowCount=40,
            validRowCount=40,
            droppedRowCount=0,
            duplicateTimeCount=0,
            missingTimeCount=0,
            timeStart=None,
            timeEnd=None,
        ),
    )


class WorkingModel:
    def fit(self, times, values, frequency):
        self.last = values[-1]

    def predict(self, horizon):
        from app.models.base import ForecastOutput

        return ForecastOutput(predictions=[self.last] * horizon)


class FitFailureModel:
    def fit(self, times, values, frequency):
        raise RuntimeError("fit exploded")

    def predict(self, horizon):
        raise AssertionError("predict should not run")


class PredictFailureModel:
    def fit(self, times, values, frequency):
        return None

    def predict(self, horizon):
        raise RuntimeError("predict exploded")


def test_fit_failure_does_not_fail_whole_backtest(monkeypatch):
    def factory(model_id):
        return FitFailureModel() if model_id == "naive" else WorkingModel()

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    result = run_holdout_backtest(series(), ["naive", "moving_average"], horizon=5, test_size=5)
    assert result.rankedModels[0].modelId == "moving_average"
    assert result.rankedModels[0].status == "success"
    failed = [model for model in result.rankedModels if model.modelId == "naive"][0]
    assert failed.status == "failed"
    assert "fit exploded" in (failed.error or "")


def test_predict_failure_does_not_fail_whole_backtest(monkeypatch):
    def factory(model_id):
        return PredictFailureModel() if model_id == "naive" else WorkingModel()

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    result = run_holdout_backtest(series(), ["naive", "moving_average"], horizon=5, test_size=5)
    failed = [model for model in result.rankedModels if model.modelId == "naive"][0]
    assert failed.status == "failed"
    assert "predict exploded" in (failed.error or "")
    assert result.recommendedModelId == "moving_average"
