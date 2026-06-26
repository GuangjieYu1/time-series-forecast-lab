from __future__ import annotations

import math

import numpy as np

from app.schemas import MetricValues


def calculate_metrics(actual: list[float], predicted: list[float]) -> tuple[MetricValues, list[str]]:
    warnings: list[str] = []
    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    residual = actual_array - predicted_array
    absolute_error = np.abs(residual)
    squared_error = residual**2
    mse = float(np.mean(squared_error))
    mae = float(np.mean(absolute_error))
    rmse = float(math.sqrt(mse))
    denominator = float(np.sum(np.abs(actual_array)))
    if denominator == 0:
        wape = None
        warnings.append("WAPE is null because sum(abs(actual)) equals zero.")
    else:
        wape = float(np.sum(absolute_error) / denominator)
    return MetricValues(mae=mae, mse=mse, rmse=rmse, wape=wape), warnings
