from __future__ import annotations

from datetime import datetime

from app.models.base import ForecastOutput
from app.models.naive import NaiveModel


class ArimaModel:
    model_id = "arima"

    def __init__(self, p: int = 1, d: int = 1, q: int = 1) -> None:
        self.model = None
        self.fallback = NaiveModel()
        self.warnings: list[str] = []
        self.order = (p, d, q)

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        try:
            from statsmodels.tsa.arima.model import ARIMA

            order = self.order if len(values) >= 8 else (min(self.order[0], 1), 0, min(self.order[2], 1))
            fitted = ARIMA(values, order=order).fit()
            self.model = fitted
        except Exception as exc:
            self.warnings.append(f"ARIMA fitting failed; used naive fallback. Reason: {exc}")
            self.fallback.fit(times, values, frequency)

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None:
            output = self.fallback.predict(horizon)
            output.warnings.extend(self.warnings)
            return output
        forecast = self.model.forecast(steps=horizon)
        return ForecastOutput(predictions=[float(value) for value in forecast], warnings=self.warnings)
