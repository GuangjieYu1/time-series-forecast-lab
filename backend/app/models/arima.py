from __future__ import annotations

from datetime import datetime

import numpy as np

from app.models.base import ForecastOutput
from app.models.naive import NaiveModel


class ArimaModel:
    model_id = "arima"

    def __init__(self, p: int = 1, d: int = 1, q: int = 1) -> None:
        self.model = None
        self.fallback = NaiveModel()
        self.warnings: list[str] = []
        self.order = (p, d, q)
        self.residual_scale = 0.0

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.model = None
        self.warnings = []
        self.residual_scale = 0.0
        try:
            from statsmodels.tsa.arima.model import ARIMA

            order = self.order if len(values) >= 8 else (min(self.order[0], 1), 0, min(self.order[2], 1))
            fitted = ARIMA(values, order=order).fit()
            self.model = fitted
            self.residual_scale = float(np.std(fitted.resid, ddof=1)) if len(fitted.resid) >= 2 else 0.0
        except Exception as exc:
            self.warnings.append(f"ARIMA fitting failed; used naive fallback. Reason: {exc}")
            self.fallback.fit(times, values, frequency)

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None:
            output = self.fallback.predict(horizon)
            output.warnings.extend(self.warnings)
            return output
        try:
            forecast_result = self.model.get_forecast(steps=horizon)
            forecast = forecast_result.predicted_mean
            confidence = np.asarray(forecast_result.conf_int(alpha=0.05), dtype=float)
            lower = confidence[:, 0].tolist()
            upper = confidence[:, 1].tolist()
        except Exception as exc:
            self.warnings.append(f"ARIMA interval generation failed; used residual band. Reason: {exc}")
            forecast = self.model.forecast(steps=horizon)
            lower = [float(value) - 1.96 * self.residual_scale for value in forecast]
            upper = [float(value) + 1.96 * self.residual_scale for value in forecast]
        return ForecastOutput(predictions=[float(value) for value in forecast], lower=lower, upper=upper, warnings=self.warnings)
