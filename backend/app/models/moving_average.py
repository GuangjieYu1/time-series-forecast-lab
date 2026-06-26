from __future__ import annotations

from datetime import datetime

import numpy as np

from app.models.base import ForecastOutput


class MovingAverageModel:
    model_id = "moving_average"

    def __init__(self, window: int = 7) -> None:
        self.window = window
        self.mean_value = 0.0

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        window = min(self.window, len(values))
        self.mean_value = float(np.mean(values[-window:]))

    def predict(self, horizon: int) -> ForecastOutput:
        return ForecastOutput(predictions=[self.mean_value] * horizon)
