from __future__ import annotations

from datetime import datetime

from app.models.base import ForecastOutput


class NaiveModel:
    model_id = "naive"

    def __init__(self) -> None:
        self.last_value = 0.0

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.last_value = float(values[-1])

    def predict(self, horizon: int) -> ForecastOutput:
        return ForecastOutput(predictions=[self.last_value] * horizon)
