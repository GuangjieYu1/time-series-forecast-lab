from __future__ import annotations

import time
from datetime import datetime
import math
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
from app.services.metrics import calculate_metrics
from app.services.model_registry import MODEL_CAPABILITIES, create_model, validate_horizon
from app.services.series_builder import TimeSeriesData


class BacktestResult(BaseModel):
    recommendedModelId: str | None
    rankedModels: list[RankedModel]
    backtest: BacktestData


class ModelProgressEvent(BaseModel):
    modelId: str
    stage: Literal["fitting", "predicting", "scoring", "success", "failed"]
    fitSeconds: float = 0.0
    predictSeconds: float = 0.0
    error: str | None = None


ProgressCallback = Callable[[ModelProgressEvent], None]


def _iso(value: datetime) -> str:
    return value.isoformat()


def run_holdout_backtest(
    series: TimeSeriesData,
    selected_models: list[str],
    horizon: int,
    test_size: int,
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

    for model_id in selected_models:
        capability = MODEL_CAPABILITIES[model_id]
        fit_seconds = 0.0
        predict_seconds = 0.0
        warnings: list[str] = []
        try:
            if progress_callback:
                progress_callback(ModelProgressEvent(modelId=model_id, stage="fitting"))
            model = create_model(model_id)
            fit_start = time.perf_counter()
            model.fit([point.time for point in train], [point.value for point in train], series.frequency)
            fit_seconds = time.perf_counter() - fit_start

            if progress_callback:
                progress_callback(
                    ModelProgressEvent(modelId=model_id, stage="predicting", fitSeconds=fit_seconds)
                )
            predict_start = time.perf_counter()
            output = model.predict(test_size)
            predict_seconds = time.perf_counter() - predict_start
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
                )
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
            ranked.append(
                RankedModel(
                    modelId=model_id,
                    modelName=capability.name,
                    metrics=None,
                    runtime=ModelRuntime(fitSeconds=round(fit_seconds, 4), predictSeconds=round(predict_seconds, 4)),
                    status="failed",
                    warnings=warnings,
                    error=str(exc),
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
