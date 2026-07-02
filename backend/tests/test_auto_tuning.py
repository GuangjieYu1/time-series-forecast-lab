from __future__ import annotations

from datetime import datetime, timedelta

import app.services.auto_tuning.service as tuning_service
from app.models.base import ForecastOutput
from app.services.deepseek import _build_tuning_appendix, build_report_context
from app.schemas import ReportOptions


def test_auto_tuning_records_trials_and_marks_selected(monkeypatch):
    class FakeModel:
        def __init__(self, parameters):
            self.value = float(parameters["window"])

        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            return ForecastOutput(predictions=[self.value] * horizon)

    monkeypatch.setattr(tuning_service, "should_isolate_model", lambda model_id: False)
    monkeypatch.setattr(tuning_service, "create_model", lambda model_id, parameters=None: FakeModel(parameters or {"window": 7}))

    result = tuning_service.resolve_model_parameters(
        model_id="moving_average",
        requested_parameters={"window": 5},
        parameter_strategy="auto",
        run_profile="balanced",
        random_seed=42,
        train_times=[datetime(2026, 1, 1) + timedelta(days=index) for index in range(40)],
        train_values=[7.0] * 40,
        frequency="D",
        test_size=5,
    )

    assert result.strategy == "auto"
    assert result.selectedParams["window"] == 7
    assert result.candidateCount == len(result.trials)
    assert result.candidateLimit >= result.candidateCount
    assert result.validationSize >= 4
    assert sum(1 for trial in result.trials if trial.selected) == 1
    assert any(trial.selected and trial.params["window"] == 7 for trial in result.trials)


def test_report_context_and_appendix_include_tuning_trials():
    experiment = {
        "experimentId": "exp_demo",
        "experimentName": "demo",
        "fileName": "demo.csv",
        "sheetName": "CSV",
        "targetColumn": "value",
        "recommendedModelId": "moving_average",
        "bestMae": 0.12,
        "createdAt": "2026-07-01T00:00:00Z",
        "config": {"parameterStrategy": "auto", "runProfile": "balanced"},
        "rankedModels": [],
        "diagnostics": {},
        "backtest": {"predictions": {}},
        "finalForecast": None,
        "modelLogs": [],
        "manifest": {
            "targets": [
                {
                    "targetColumn": "value",
                    "detectedFrequency": "D",
                    "recommendedModelId": "moving_average",
                    "models": [
                        {
                            "modelId": "moving_average",
                            "modelName": "Moving Average",
                            "rank": 1,
                            "status": "success",
                            "metrics": {"mae": 0.12, "mse": 0.03, "rmse": 0.1732, "wape": 0.02},
                            "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01},
                            "warnings": [],
                            "error": None,
                            "tuning": {
                                "enabled": True,
                                "profile": "balanced",
                                "strategy": "auto",
                                "selectedParams": {"window": 7},
                                "candidateCount": 3,
                                "bestMetric": 0.12,
                                "tuningSeconds": 0.23,
                                "candidateLimit": 7,
                                "timeBudgetSeconds": 8.0,
                                "validationSize": 5,
                                "stoppedEarly": False,
                                "warnings": [],
                                "trials": [
                                    {
                                        "round": 1,
                                        "params": {"window": 5},
                                        "status": "success",
                                        "metrics": {"mae": 0.3, "mse": 0.1, "rmse": 0.3162, "wape": 0.04},
                                        "elapsedSeconds": 0.02,
                                        "selected": False,
                                        "message": "评估成功。",
                                    },
                                    {
                                        "round": 2,
                                        "params": {"window": 7},
                                        "status": "success",
                                        "metrics": {"mae": 0.12, "mse": 0.03, "rmse": 0.1732, "wape": 0.02},
                                        "elapsedSeconds": 0.02,
                                        "selected": True,
                                        "message": "评估成功。",
                                    },
                                ],
                            },
                        }
                    ],
                }
            ]
        },
    }

    context = build_report_context(experiment)
    appendix = _build_tuning_appendix(context, ReportOptions())

    assert context["autoTuning"]["enabled"] is True
    assert context["autoTuning"]["trialCount"] == 2
    assert context["targets"][0]["models"][0]["tuning"]["trials"][1]["selected"] is True
    assert "附录：自动优化策略与逐轮结果" in appendix
    assert '"window": 7' in appendix
    assert "| 2 | success | 是 | 0.1200 |" in appendix


def test_seasonal_naive_auto_tuning_generates_multiple_period_candidates(monkeypatch):
    class FakeSeasonalNaiveModel:
        def __init__(self, period=None):
            self.period = int(period or 7)

        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            return ForecastOutput(predictions=[float(self.period)] * horizon)

    monkeypatch.setattr(tuning_service, "should_isolate_model", lambda model_id: False)
    monkeypatch.setattr(tuning_service, "create_model", lambda model_id, parameters=None: FakeSeasonalNaiveModel(**(parameters or {})))

    result = tuning_service.resolve_model_parameters(
        model_id="seasonal_naive",
        requested_parameters={"period": 0},
        parameter_strategy="auto",
        run_profile="balanced",
        random_seed=42,
        train_times=[datetime(2026, 1, 1) + timedelta(days=index) for index in range(80)],
        train_values=[7.0] * 80,
        frequency="D",
        test_size=7,
    )

    assert result.strategy == "auto"
    assert result.candidateCount > 1
    assert all(trial.params["period"] >= 1 for trial in result.trials)
    assert any(trial.params["period"] == 7 for trial in result.trials)
    assert any(trial.params["period"] == 14 for trial in result.trials)


def test_timesfm_auto_tuning_generates_multiple_candidates(monkeypatch):
    class FakeTimesFmModel:
        def __init__(self, max_context=512, normalize_inputs=True):
            self.max_context = int(max_context)
            self.normalize_inputs = bool(normalize_inputs)

        def fit(self, times, values, frequency):
            return None

        def predict(self, horizon):
            value = float(self.max_context + (0 if self.normalize_inputs else 1))
            return ForecastOutput(predictions=[value] * horizon)

    monkeypatch.setattr(tuning_service, "should_isolate_model", lambda model_id: False)
    monkeypatch.setattr(tuning_service, "create_model", lambda model_id, parameters=None: FakeTimesFmModel(**(parameters or {})))

    result = tuning_service.resolve_model_parameters(
        model_id="timesfm",
        requested_parameters={"maxContext": 512, "normalizeInputs": True},
        parameter_strategy="auto",
        run_profile="balanced",
        random_seed=42,
        train_times=[datetime(2026, 1, 1) + timedelta(days=index) for index in range(96)],
        train_values=[32.0] * 96,
        frequency="D",
        test_size=8,
    )

    assert result.strategy == "auto"
    assert result.candidateCount > 1
    assert any(trial.params["normalizeInputs"] is False for trial in result.trials)
    assert any(trial.params["maxContext"] == 32 for trial in result.trials)
    assert all(trial.params["maxContext"] <= 88 for trial in result.trials)
