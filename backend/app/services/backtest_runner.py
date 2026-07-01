from __future__ import annotations

import time
from datetime import datetime
import math
import logging
from typing import Callable, Literal

from pydantic import BaseModel

from app.core.errors import AppError
from app.schemas import (
    BacktestActualPoint,
    BacktestData,
    BacktestPredictionPoint,
    ModelRuntime,
    RankedModel,
)
from app.services.auto_tuning import resolve_model_parameters
from app.services.metrics import calculate_metrics
from app.services.model_registry import MODEL_CAPABILITIES, create_model, validate_horizon
from app.services.model_executor import run_isolated_fit_predict, should_isolate_model
from app.services.series_builder import TimeSeriesData


class BacktestResult(BaseModel):
    recommendedModelId: str | None
    rankedModels: list[RankedModel]
    backtest: BacktestData


class ModelProgressEvent(BaseModel):
    modelId: str
    stage: Literal["tuning", "fitting", "predicting", "scoring", "success", "failed"]
    progressPercent: int | None = None
    message: str | None = None
    fitSeconds: float = 0.0
    predictSeconds: float = 0.0
    error: str | None = None


ProgressCallback = Callable[[ModelProgressEvent], None]
logger = logging.getLogger(__name__)


def _iso(value: datetime) -> str:
    return value.isoformat()


def run_holdout_backtest(
    series: TimeSeriesData,
    selected_models: list[str],
    horizon: int,
    test_size: int,
    model_parameters: dict[str, dict] | None = None,
    parameter_strategy: str = "default",
    run_profile: str = "balanced",
    random_seed: int = 42,
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    if not selected_models:
        raise AppError("Select at least one model before running the experiment.")
    unknown = [model_id for model_id in selected_models if model_id not in MODEL_CAPABILITIES]
    if unknown:
        raise AppError(f"Unknown model ids: {', '.join(unknown)}")
    try:
        validate_horizon(selected_models, horizon)
    except ValueError as exc:
        raise AppError(str(exc)) from exc

    points = series.points
    if test_size < 1:
        raise AppError("Test size must be at least 1.")
    if len(points) <= test_size:
        raise AppError("Test size is too large for the available time series length.")
    train = points[:-test_size]
    test = points[-test_size:]
    min_train_size = 30
    if len(train) < min_train_size:
        series.diagnostics.warnings.append("Training points are fewer than 30; model comparison may be unstable.")

    actual_values = [point.value for point in test]
    actual = [BacktestActualPoint(time=_iso(point.time), value=point.value) for point in test]
    predictions: dict[str, list[BacktestPredictionPoint]] = {}
    ranked: list[RankedModel] = []
    parameters_by_model = model_parameters or {}

    for model_id in selected_models:
        capability = MODEL_CAPABILITIES[model_id]
        fit_seconds = 0.0
        predict_seconds = 0.0
        warnings: list[str] = []

        def report_tuning_progress(completed: int, total: int, message: str):
            if not progress_callback:
                return
            total_count = max(total, 1)
            percent = min(100, max(0, int((completed / total_count) * 100)))
            progress_callback(
                ModelProgressEvent(
                    modelId=model_id,
                    stage="tuning",
                    progressPercent=percent,
                    message=message,
                )
            )

        tuning = resolve_model_parameters(
            model_id=model_id,
            requested_parameters=parameters_by_model.get(model_id),
            parameter_strategy=parameter_strategy,
            run_profile=run_profile,
            random_seed=random_seed,
            train_times=[point.time for point in train],
            train_values=[point.value for point in train],
            frequency=series.frequency,
            test_size=test_size,
            progress_callback=report_tuning_progress,
        )
        selected_parameters = tuning.selectedParams
        warnings.extend(tuning.warnings)
        try:
            logger.info(
                "model run started target=%s model=%s frequency=%s train_points=%s test_size=%s horizon=%s isolated=%s",
                series.targetColumn,
                model_id,
                series.frequency,
                len(train),
                test_size,
                horizon,
                should_isolate_model(model_id),
            )
            if progress_callback:
                progress_callback(ModelProgressEvent(modelId=model_id, stage="fitting"))
            train_times = [point.time for point in train]
            train_values = [point.value for point in train]
            if should_isolate_model(model_id):
                output = run_isolated_fit_predict(
                    model_id,
                    selected_parameters,
                    train_times,
                    train_values,
                    series.frequency,
                    test_size,
                )
                fit_seconds = output.fit_seconds
                predict_seconds = output.predict_seconds
            else:
                model = create_model(model_id, selected_parameters)
                fit_start = time.perf_counter()
                model.fit(train_times, train_values, series.frequency)
                fit_seconds = time.perf_counter() - fit_start

                if progress_callback:
                    progress_callback(
                        ModelProgressEvent(modelId=model_id, stage="predicting", fitSeconds=fit_seconds)
                    )
                predict_start = time.perf_counter()
                output = model.predict(test_size)
                predict_seconds = time.perf_counter() - predict_start
            if should_isolate_model(model_id) and progress_callback:
                progress_callback(ModelProgressEvent(modelId=model_id, stage="predicting", fitSeconds=fit_seconds))
            warnings.extend(output.warnings)

            predicted_values = [float(value) for value in output.predictions[:test_size]]
            if len(predicted_values) != test_size:
                raise RuntimeError(f"Model returned {len(predicted_values)} points for test size {test_size}.")
            if any(not math.isfinite(value) for value in predicted_values):
                raise RuntimeError("Model returned NaN or infinite predictions.")
            if progress_callback:
                progress_callback(
                    ModelProgressEvent(
                        modelId=model_id,
                        stage="scoring",
                        fitSeconds=fit_seconds,
                        predictSeconds=predict_seconds,
                    )
                )
            metrics, metric_warnings = calculate_metrics(actual_values, predicted_values)
            if metrics.mae is not None and not math.isfinite(metrics.mae):
                raise RuntimeError("Model metrics are not finite.")
            warnings.extend(metric_warnings)

            model_points: list[BacktestPredictionPoint] = []
            for point, predicted in zip(test, predicted_values):
                residual = float(point.value - predicted)
                model_points.append(
                    BacktestPredictionPoint(
                        time=_iso(point.time),
                        predicted=predicted,
                        actual=point.value,
                        residual=residual,
                        absoluteError=abs(residual),
                        squaredError=residual * residual,
                    )
                )
            predictions[model_id] = model_points
            ranked.append(
                RankedModel(
                    modelId=model_id,
                    modelName=capability.name,
                    metrics=metrics,
                    runtime=ModelRuntime(fitSeconds=round(fit_seconds, 4), predictSeconds=round(predict_seconds, 4)),
                    status="success",
                    warnings=warnings,
                    tuning=tuning,
                )
            )
            logger.info(
                "model run completed target=%s model=%s fit_seconds=%.4f predict_seconds=%.4f",
                series.targetColumn,
                model_id,
                fit_seconds,
                predict_seconds,
            )
            if progress_callback:
                progress_callback(
                    ModelProgressEvent(
                        modelId=model_id,
                        stage="success",
                        fitSeconds=fit_seconds,
                        predictSeconds=predict_seconds,
                    )
                )
        except Exception as exc:
            logger.exception(
                "model run failed target=%s model=%s frequency=%s train_points=%s test_size=%s horizon=%s",
                series.targetColumn,
                model_id,
                series.frequency,
                len(train),
                test_size,
                horizon,
            )
            ranked.append(
                RankedModel(
                    modelId=model_id,
                    modelName=capability.name,
                    metrics=None,
                    runtime=ModelRuntime(fitSeconds=round(fit_seconds, 4), predictSeconds=round(predict_seconds, 4)),
                    status="failed",
                    warnings=warnings,
                    error=str(exc),
                    tuning=tuning,
                )
            )
            if progress_callback:
                progress_callback(
                    ModelProgressEvent(
                        modelId=model_id,
                        stage="failed",
                        fitSeconds=fit_seconds,
                        predictSeconds=predict_seconds,
                        error=str(exc),
                    )
                )

    successful = [item for item in ranked if item.status == "success" and item.metrics and item.metrics.mae is not None]
    successful.sort(key=lambda item: item.metrics.mae if item.metrics and item.metrics.mae is not None else float("inf"))
    for index, item in enumerate(successful, start=1):
        item.rank = index
    failed = [item for item in ranked if item.status != "success" or not item.metrics]
    ranked_models = successful + failed
    recommended = successful[0].modelId if successful else None
    return BacktestResult(
        recommendedModelId=recommended,
        rankedModels=ranked_models,
        backtest=BacktestData(actual=actual, predictions=predictions),
    )
