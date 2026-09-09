from __future__ import annotations

from datetime import datetime

import numpy as np

from app.models.base import ForecastOutput


class MovingAverageModel:
    model_id = "moving_average"

    def __init__(self, window: int = 7) -> None:
        self.window = window
        self.mean_value = 0.0
        self.residual_scale = 0.0

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.residual_scale = 0.0
        window = min(self.window, len(values))
        self.mean_value = float(np.mean(values[-window:]))
        if len(values) > window:
            residuals = [
                float(values[index]) - float(np.mean(values[index - window:index]))
                for index in range(window, len(values))
            ]
            self.residual_scale = float(np.std(residuals, ddof=1)) if len(residuals) >= 2 else float(abs(residuals[0]))

    def predict(self, horizon: int) -> ForecastOutput:
        predictions = [self.mean_value] * horizon
        lower = [self.mean_value - 1.96 * self.residual_scale] * horizon
        upper = [self.mean_value + 1.96 * self.residual_scale] * horizon
        return ForecastOutput(predictions=predictions, lower=lower, upper=upper)
