from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Literal

import pandas as pd

from app.core.errors import AppError
from app.schemas import FinalForecastResponse, ForecastPoint, HistoryPoint
from app.services.model_executor import fit_model_instance, predict_model_instance, run_isolated_fit_predict, should_isolate_model
from app.services.model_registry import MODEL_CAPABILITIES, create_model, validate_horizon
from app.services.series_builder import PANDAS_FREQ


FinalProgressCallback = Callable[[Literal["fitting", "predicting"]], None]
logger = logging.getLogger(__name__)


def _future_times(last_time: datetime, frequency: str, horizon: int) -> list[datetime]:
    freq = PANDAS_FREQ.get(frequency, "D")
    dates = pd.date_range(last_time, periods=horizon + 1, freq=freq)[1:]
    return [date.to_pydatetime() for date in dates]


def run_final_forecast(
    experiment_id: str,
    final_model_id: str,
    horizon: int,
    frequency: str,
    history: list[dict],
    model_parameters: dict[str, dict] | None = None,
    covariate_history: list[dict[str, float]] | None = None,
    feature_config: dict[str, bool] | None = None,
    progress_callback: FinalProgressCallback | None = None,
) -> FinalForecastResponse:
    if final_model_id not in MODEL_CAPABILITIES:
        raise AppError(f"Unknown model id: {final_model_id}.")
    try:
        validate_horizon([final_model_id], horizon)
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    if len(history) < 2:
        raise AppError("Not enough saved aggregated history to run final forecast.")

    times = [datetime.fromisoformat(point["time"]) for point in history]
    values = [float(point["value"]) for point in history]
    model_params = (model_parameters or {}).get(final_model_id)
    try:
        if progress_callback:
            progress_callback("fitting")
        logger.info(
            "final model run started experiment_id=%s model=%s frequency=%s points=%s horizon=%s isolated=%s",
            experiment_id,
            final_model_id,
            frequency,
            len(history),
            horizon,
            should_isolate_model(final_model_id),
        )
        if should_isolate_model(final_model_id):
            output = run_isolated_fit_predict(
                final_model_id,
                model_params,
                times,
                values,
                frequency,
                horizon,
                covariates=covariate_history,
                feature_config=feature_config,
            )
            if progress_callback:
                progress_callback("predicting")
        else:
            model = create_model(final_model_id, model_params)
            fit_model_instance(
                final_model_id,
                model,
                times,
                values,
                frequency,
                covariates=covariate_history,
                feature_config=feature_config,
            )
            if progress_callback:
                progress_callback("predicting")
            output = predict_model_instance(final_model_id, model, horizon)
    except Exception as exc:
        logger.exception(
            "final model run failed experiment_id=%s model=%s frequency=%s points=%s horizon=%s",
            experiment_id,
            final_model_id,
            frequency,
            len(history),
            horizon,
        )
        raise AppError(f"Final model failed: {exc}") from exc
    logger.info(
        "final model run completed experiment_id=%s model=%s horizon=%s",
        experiment_id,
        final_model_id,
        horizon,
    )

    future = _future_times(times[-1], frequency, horizon)
    lower = output.lower or [None] * horizon
    upper = output.upper or [None] * horizon
    forecast = [
        ForecastPoint(
            time=future[index].isoformat(),
            predicted=float(output.predictions[index]),
            lower=float(lower[index]) if index < len(lower) and lower[index] is not None else None,
            upper=float(upper[index]) if index < len(upper) and upper[index] is not None else None,
        )
        for index in range(horizon)
    ]
    capability = MODEL_CAPABILITIES[final_model_id]
    return FinalForecastResponse(
        experimentId=experiment_id,
        finalModelId=final_model_id,
        history=[HistoryPoint(time=point["time"], value=float(point["value"])) for point in history],
        forecast=forecast,
        modelInfo={"name": capability.name, "supportsPredictionInterval": capability.supportsPredictionInterval},
    )
