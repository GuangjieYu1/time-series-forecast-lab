from __future__ import annotations

from datetime import datetime

from app.models.base import ForecastOutput
from app.models.naive import NaiveModel


class ArimaModel:
    model_id = "arima"

    def __init__(self) -> None:
        self.model = None
        self.fallback = NaiveModel()
        self.warnings: list[str] = []

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        try:
            from statsmodels.tsa.arima.model import ARIMA

            order = (1, 1, 1) if len(values) >= 8 else (1, 0, 0)
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
