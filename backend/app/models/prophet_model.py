from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from app.models.base import ForecastOutput


PANDAS_FREQ = {
    "H": "h",
    "D": "D",
    "W": "W-MON",
    "M": "MS",
    "Q": "QS",
    "Y": "YS",
}


class ProphetModel:
    model_id = "prophet"

    def __init__(self) -> None:
        self.model = None
        self.frequency = "D"
        self.last_time: datetime | None = None
        self.values: list[float] = []
        self.warnings: list[str] = []

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.frequency = frequency
        self.last_time = times[-1]
        self.values = [float(value) for value in values]
        try:
            from prophet import Prophet

            frame = pd.DataFrame({"ds": times, "y": values})
            model = Prophet(interval_width=0.8, daily_seasonality=False, weekly_seasonality="auto", yearly_seasonality="auto")
            model.fit(frame)
            self.model = model
        except Exception as exc:
            raise RuntimeError(f"Prophet is unavailable or failed to fit: {exc}") from exc

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None or self.last_time is None:
            raise RuntimeError("Prophet model was not fitted.")
        future = self.model.make_future_dataframe(periods=horizon, freq=PANDAS_FREQ.get(self.frequency, "D"), include_history=False)
        forecast = self.model.predict(future)
        predictions = [float(value) for value in forecast["yhat"].tolist()]
        lower = [float(value) for value in forecast.get("yhat_lower", pd.Series([np.nan] * horizon)).tolist()]
        upper = [float(value) for value in forecast.get("yhat_upper", pd.Series([np.nan] * horizon)).tolist()]
        return ForecastOutput(predictions=predictions, lower=lower, upper=upper, warnings=self.warnings)
