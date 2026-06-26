from __future__ import annotations

from datetime import datetime

from app.models.base import ForecastOutput


SEASONAL_PERIODS = {
    "H": 24,
    "D": 7,
    "W": 52,
    "M": 12,
    "Q": 4,
    "Y": 1,
}


class SeasonalNaiveModel:
    model_id = "seasonal_naive"

    def __init__(self) -> None:
        self.values: list[float] = []
        self.period = 1
        self.warnings: list[str] = []

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.values = [float(value) for value in values]
        self.period = SEASONAL_PERIODS.get(frequency, 1)
        if len(self.values) < self.period:
            self.warnings.append("Not enough history for a full seasonal period; fell back to naive repetition.")
            self.period = 1

    def predict(self, horizon: int) -> ForecastOutput:
        predictions = []
        for step in range(horizon):
            predictions.append(self.values[-self.period + (step % self.period)])
        return ForecastOutput(predictions=predictions, warnings=self.warnings)
