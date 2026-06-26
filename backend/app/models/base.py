from __future__ import annotations

from datetime import datetime
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field


class ForecastOutput(BaseModel):
    predictions: list[float]
    lower: list[float | None] = Field(default_factory=list)
    upper: list[float | None] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ForecastModel(Protocol):
    model_id: str

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        ...

    def predict(self, horizon: int) -> ForecastOutput:
        ...


def residual_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.std(np.asarray(values, dtype=float), ddof=1))
