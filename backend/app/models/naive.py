from __future__ import annotations

from datetime import datetime

import numpy as np

from app.models.base import ForecastOutput


class NaiveModel:
    model_id = "naive"

    def __init__(self) -> None:
        self.last_value = 0.0
        self.residual_scale = 0.0

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.last_value = float(values[-1])
        self.residual_scale = 0.0
        if len(values) >= 2:
            diffs = [float(values[index]) - float(values[index - 1]) for index in range(1, len(values))]
            self.residual_scale = float(np.std(diffs, ddof=1)) if len(diffs) >= 2 else abs(diffs[0])

    def predict(self, horizon: int) -> ForecastOutput:
        predictions = [self.last_value] * horizon
        lower = [self.last_value - 1.96 * self.residual_scale] * horizon
        upper = [self.last_value + 1.96 * self.residual_scale] * horizon
        return ForecastOutput(predictions=predictions, lower=lower, upper=upper)
