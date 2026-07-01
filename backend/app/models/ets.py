from __future__ import annotations

from datetime import datetime

import numpy as np

from app.models.base import ForecastOutput
from app.models.moving_average import MovingAverageModel


class EtsModel:
    model_id = "ets"

    def __init__(self, trend: str = "auto") -> None:
        self.model = None
        self.values: list[float] = []
        self.fallback = MovingAverageModel()
        self.trend = trend
        self.warnings: list[str] = []

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.values = [float(value) for value in values]
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            trend = "add" if self.trend == "add" or (self.trend == "auto" and len(values) >= 10) else None
            fitted = ExponentialSmoothing(values, trend=trend, seasonal=None, initialization_method="estimated").fit()
            self.model = fitted
        except Exception as exc:
            self.warnings.append(f"ETS fitting failed; used moving average fallback. Reason: {exc}")
            self.fallback.fit(times, values, frequency)

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None:
            output = self.fallback.predict(horizon)
            output.warnings.extend(self.warnings)
            return output
        forecast = [float(value) for value in self.model.forecast(horizon)]
        sigma = float(np.std(self.values, ddof=1)) if len(self.values) > 1 else 0.0
        lower = [value - 1.96 * sigma for value in forecast]
        upper = [value + 1.96 * sigma for value in forecast]
        return ForecastOutput(predictions=forecast, lower=lower, upper=upper, warnings=self.warnings)
