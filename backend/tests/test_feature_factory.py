from datetime import datetime, timedelta, timezone

import numpy as np

from app.schemas import Diagnostics, ModelProgress, RuntimeFeaturePipelineTarget
from app.services.backtest_runner import run_holdout_backtest
from app.services.feature_factory import build_feature_factory
from app.services.runtime_tracker import RuntimeTracker
from app.services.series_builder import TimeSeriesData, TimeSeriesPoint


def _times(count: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=index) for index in range(count)]


def _pipeline() -> RuntimeFeaturePipelineTarget:
    return RuntimeFeaturePipelineTarget(targetColumn="value", detectedFrequency="D")


def test_shared_feature_factory_emits_real_steps_and_uses_only_prior_targets():
    times = _times(40)
    values = [float(index + 1) for index in range(40)]
    snapshots = []

    result = build_feature_factory(
        pipeline=_pipeline(),
        times=times,
        values=values,
        frequency="D",
        covariates=None,
        feature_config={"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "covariates": True},
        selected_model_ids=["xgboost", "lightgbm"],
        progress_callback=snapshots.append,
    )

    assert result.error is None
    assert result.prepared is not None
    assert result.pipeline.status == "completed"
    assert result.pipeline.traceMode == "live"
    assert result.pipeline.progressPercent == 100
    assert all(step.description for step in result.pipeline.steps)
    assert [step.id for step in result.pipeline.steps] == [
        "source_alignment",
        "covariate_loader",
        "calendar_generator",
        "holiday_generator",
        "lag_generator",
        "rolling_generator",
        "feature_merge",
        "leakage_guard",
        "feature_selection",
        "matrix_ready",
    ]
    assert next(step for step in result.pipeline.steps if step.id == "covariate_loader").status == "skipped"
    assert next(step for step in result.pipeline.steps if step.id == "holiday_generator").status == "completed"
    assert next(step for step in result.pipeline.steps if step.id == "holiday_generator").visualization is not None
    assert next(step for step in result.pipeline.steps if step.id == "leakage_guard").status == "completed"
    assert any(step.currentStepId == "lag_generator" and step.steps[4].status == "running" for step in snapshots)

    prepared = result.prepared
    assert prepared.startIndex == 7
    assert prepared.featureNames[:7] == [
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_7",
        "rolling_mean_3",
        "rolling_mean_7",
        "rolling_std_7",
    ]
    first = prepared.featureValues[0]
    assert first[0] == 7.0
    assert first[1] == 6.0
    assert first[2] == 5.0
    assert first[3] == 1.0
    assert first[4] == 6.0
    assert first[5] == 4.0
    assert first[6] == np.std(np.arange(1.0, 8.0), ddof=0)
    assert prepared.targets[0] == 8.0

    matrix_step = next(step for step in result.pipeline.steps if step.id == "matrix_ready")
    assert matrix_step.outputProfile is not None
    assert matrix_step.outputProfile.rowCount == 33
    assert matrix_step.outputProfile.columnCount == len(prepared.featureNames)
    assert not hasattr(matrix_step.outputProfile, "rows")


def test_feature_factory_without_consumers_marks_selection_and_matrix_skipped():
    result = build_feature_factory(
        pipeline=_pipeline(),
        times=_times(35),
        values=[float(index) for index in range(35)],
        frequency="D",
        covariates=None,
        feature_config=None,
        selected_model_ids=["naive", "ets"],
    )

    assert result.error is None
    assert result.prepared is None
    assert next(step for step in result.pipeline.steps if step.id == "feature_selection").status == "skipped"
    assert next(step for step in result.pipeline.steps if step.id == "matrix_ready").status == "skipped"


def test_feature_factory_failure_only_fails_feature_consuming_models():
    times = _times(40)
    values = [float(index + 1) for index in range(40)]
    result = build_feature_factory(
        pipeline=_pipeline(),
        times=times[:-7],
        values=values[:-7],
        frequency="D",
        covariates=[{"static_value": 1.0}],
        feature_config=None,
        selected_model_ids=["naive", "xgboost"],
    )
    assert result.error is not None

    series = TimeSeriesData(
        targetColumn="value",
        frequency="D",
        points=[TimeSeriesPoint(time=time, value=value) for time, value in zip(times, values)],
        diagnostics=Diagnostics(
            originalRowCount=40,
            validRowCount=40,
            droppedRowCount=0,
            duplicateTimeCount=0,
            missingTimeCount=0,
            timeStart=times[0].isoformat(),
            timeEnd=times[-1].isoformat(),
            warnings=[],
        ),
    )
    backtest = run_holdout_backtest(
        series,
        ["naive", "xgboost"],
        horizon=7,
        test_size=7,
        feature_factory_error=result.error,
    )
    statuses = {model.modelId: model.status for model in backtest.rankedModels}
    assert statuses == {"naive": "success", "xgboost": "failed"}
    assert "xgboost" not in backtest.backtest.predictions


def test_runtime_tracker_records_feature_step_payloads_in_order():
    tracker = RuntimeTracker()
    tracker.start(
        "run_feature_events",
        kind="backtest",
        model_rows=[ModelProgress(modelId="naive", modelName="Naive", targetColumn="value")],
        message="Starting",
    )
    result = build_feature_factory(
        pipeline=_pipeline(),
        times=_times(35),
        values=[float(index) for index in range(35)],
        frequency="D",
        covariates=None,
        feature_config=None,
        selected_model_ids=["naive"],
        progress_callback=lambda snapshot: tracker.set_feature_pipeline("run_feature_events", snapshot),
    )
    tracker.set_feature_pipeline("run_feature_events", result.pipeline)
    detail = tracker.finalize("run_feature_events", status="completed", message="Finished")

    assert detail is not None
    feature_events = [event for event in detail.events if event.eventType == "feature"]
    assert feature_events
    assert [event.sequence for event in detail.events] == list(range(1, len(detail.events) + 1))
    assert any(event.payload.get("action") == "running" for event in feature_events)
    assert any((event.payload.get("step") or {}).get("id") == "leakage_guard" for event in feature_events)
    assert feature_events[-1].payload.get("pipelineProgressPercent") == 100