from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal

import pandas as pd

from app.core.errors import AppError
from app.schemas import FinalForecastResponse, ForecastPoint, HistoryPoint
from app.services.model_registry import MODEL_CAPABILITIES, create_model, validate_horizon
from app.services.series_builder import PANDAS_FREQ


FinalProgressCallback = Callable[[Literal["fitting", "predicting"]], None]


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
    model = create_model(final_model_id)
    try:
        if progress_callback:
            progress_callback("fitting")
        model.fit(times, values, frequency)
        if progress_callback:
            progress_callback("predicting")
        output = model.predict(horizon)
    except Exception as exc:
        raise AppError(f"Final model failed: {exc}") from exc

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
