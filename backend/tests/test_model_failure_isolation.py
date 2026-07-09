from __future__ import annotations

import logging
from datetime import datetime, timedelta

import app.services.backtest_runner as backtest_runner
from app.services.model_executor import IsolatedModelResult
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
    def factory(model_id, parameters=None):
        return FitFailureModel() if model_id == "naive" else WorkingModel()

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    result = run_holdout_backtest(series(), ["naive", "moving_average"], horizon=5, test_size=5)
    assert result.rankedModels[0].modelId == "moving_average"
    assert result.rankedModels[0].status == "success"
    failed = [model for model in result.rankedModels if model.modelId == "naive"][0]
    assert failed.status == "failed"
    assert "fit exploded" in (failed.error or "")


def test_predict_failure_does_not_fail_whole_backtest(monkeypatch):
    def factory(model_id, parameters=None):
        return PredictFailureModel() if model_id == "naive" else WorkingModel()

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    result = run_holdout_backtest(series(), ["naive", "moving_average"], horizon=5, test_size=5)
    failed = [model for model in result.rankedModels if model.modelId == "naive"][0]
    assert failed.status == "failed"
    assert "predict exploded" in (failed.error or "")
    assert result.recommendedModelId == "moving_average"


def test_isolated_model_failure_does_not_fail_whole_backtest(monkeypatch, caplog):
    def factory(model_id, parameters=None):
        return WorkingModel()

    def isolated_runner(*args, **kwargs):
        raise RuntimeError("isolated model stopped unexpectedly")

    monkeypatch.setattr(backtest_runner, "create_model", factory)
    monkeypatch.setattr(backtest_runner, "should_isolate_model", lambda model_id: model_id == "xgboost")
    monkeypatch.setattr(backtest_runner, "run_isolated_fit_predict", isolated_runner)

    caplog.set_level(logging.ERROR)
    result = run_holdout_backtest(series(), ["moving_average", "xgboost"], horizon=5, test_size=5)
    assert result.recommendedModelId == "moving_average"
    failed = [model for model in result.rankedModels if model.modelId == "xgboost"][0]
    assert failed.status == "failed"
    assert "isolated model stopped unexpectedly" in (failed.error or "")
    assert "model run failed" in caplog.text
    assert "model=xgboost" in caplog.text


def test_isolated_model_success_is_scored(monkeypatch):
    def isolated_runner(*args, **kwargs):
        return IsolatedModelResult(
            predictions=[35.0, 36.0, 37.0, 38.0, 39.0],
            lower=[],
            upper=[],
            warnings=["isolated"],
            fit_seconds=0.1,
            predict_seconds=0.2,
            prediction_features=[],
        )

    monkeypatch.setattr(backtest_runner, "should_isolate_model", lambda model_id: model_id == "xgboost")
    monkeypatch.setattr(backtest_runner, "run_isolated_fit_predict", isolated_runner)

    result = run_holdout_backtest(series(), ["xgboost"], horizon=5, test_size=5)
    assert result.rankedModels[0].modelId == "xgboost"
    assert result.rankedModels[0].status == "success"
    assert result.rankedModels[0].warnings == ["isolated"]
