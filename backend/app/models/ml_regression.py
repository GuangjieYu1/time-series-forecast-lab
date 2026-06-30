from __future__ import annotations

from datetime import datetime
from typing import Any

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

WEB_WORKER_N_JOBS = 1


class LagFeatureRegressor:
    model_id = "lag_feature_regressor"
    package_name = ""
    unavailable_message = "Regression package is not installed."

    def __init__(self) -> None:
        self.model: Any = None
        self.times: list[datetime] = []
        self.values: list[float] = []
        self.frequency = "D"
        self.feature_columns = [
            "lag_1",
            "lag_2",
            "lag_3",
            "lag_7",
            "rolling_mean_3",
            "rolling_mean_7",
            "rolling_std_7",
            "time_index",
            "day_of_week",
            "month",
        ]
        self.residual_scale = 0.0
        self.warnings = ["机器学习模型使用 lag 特征、滚动统计和时间特征进行递归多步预测。"]

    def build_model(self):
        raise NotImplementedError

    def _features_for(self, values: list[float], target_time: datetime, time_index: int) -> list[float]:
        series = [float(value) for value in values]

        def lag(offset: int) -> float:
            if len(series) >= offset:
                return series[-offset]
            return series[-1]

        last_3 = series[-3:] if len(series) >= 3 else series
        last_7 = series[-7:] if len(series) >= 7 else series
        rolling_std = float(np.std(np.asarray(last_7, dtype=float), ddof=0)) if len(last_7) > 1 else 0.0
        return [
            lag(1),
            lag(2),
            lag(3),
            lag(7),
            float(np.mean(last_3)),
            float(np.mean(last_7)),
            rolling_std,
            float(time_index),
            float(target_time.weekday()),
            float(target_time.month),
        ]

    def _training_matrix(self) -> tuple[np.ndarray, np.ndarray]:
        if len(self.values) < 14:
            raise RuntimeError("At least 14 training points are required for lag-feature regression models.")
        rows: list[list[float]] = []
        targets: list[float] = []
        for index in range(7, len(self.values)):
            history = self.values[:index]
            rows.append(self._features_for(history, self.times[index], index))
            targets.append(self.values[index])
        return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float)

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.times = list(times)
        self.values = [float(value) for value in values]
        self.frequency = frequency
        self.model = self.build_model()
        features, targets = self._training_matrix()
        feature_frame = pd.DataFrame(features, columns=self.feature_columns)
        self.model.fit(feature_frame, targets)
        fitted = np.asarray(self.model.predict(feature_frame), dtype=float)
        residuals = targets - fitted
        self.residual_scale = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    def _future_times(self, horizon: int) -> list[datetime]:
        freq = PANDAS_FREQ.get(self.frequency, "D")
        dates = pd.date_range(self.times[-1], periods=horizon + 1, freq=freq)[1:]
        return [date.to_pydatetime() for date in dates]

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None:
            raise RuntimeError("Model was not fitted.")
        history = list(self.values)
        predictions: list[float] = []
        lower: list[float | None] = []
        upper: list[float | None] = []
        future_times = self._future_times(horizon)
        for step, future_time in enumerate(future_times):
            features = pd.DataFrame(
                [self._features_for(history, future_time, len(history) + step)],
                columns=self.feature_columns,
            )
            predicted = float(np.asarray(self.model.predict(features), dtype=float)[0])
            if not np.isfinite(predicted):
                raise RuntimeError("Model returned NaN or infinite predictions.")
            predictions.append(predicted)
            history.append(predicted)
            if self.residual_scale > 0:
                lower.append(predicted - 1.96 * self.residual_scale)
                upper.append(predicted + 1.96 * self.residual_scale)
            else:
                lower.append(None)
                upper.append(None)
        return ForecastOutput(predictions=predictions, lower=lower, upper=upper, warnings=self.warnings)


class XGBoostModel(LagFeatureRegressor):
    model_id = "xgboost"
    package_name = "xgboost"
    unavailable_message = "XGBoost is not installed. Install optional dependency 'xgboost' to enable this model."

    def __init__(self, n_estimators: int = 200, max_depth: int = 3, learning_rate: float = 0.05) -> None:
        super().__init__()
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate

    def build_model(self):
        try:
            from xgboost import XGBRegressor
        except Exception as exc:
            raise RuntimeError(self.unavailable_message) from exc
        return XGBRegressor(
            objective="reg:squarederror",
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=WEB_WORKER_N_JOBS,
            verbosity=0,
        )


class LightGbmModel(LagFeatureRegressor):
    model_id = "lightgbm"
    package_name = "lightgbm"
    unavailable_message = "LightGBM is not installed. Install optional dependency 'lightgbm' to enable this model."

    def __init__(self, n_estimators: int = 250, num_leaves: int = 31, learning_rate: float = 0.05) -> None:
        super().__init__()
        self.n_estimators = n_estimators
        self.num_leaves = num_leaves
        self.learning_rate = learning_rate

    def build_model(self):
        try:
            from lightgbm import LGBMRegressor
        except Exception as exc:
            raise RuntimeError(self.unavailable_message) from exc
        return LGBMRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            num_leaves=self.num_leaves,
            random_state=42,
            n_jobs=WEB_WORKER_N_JOBS,
            verbose=-1,
        )


class RandomForestTsModel(LagFeatureRegressor):
    model_id = "random_forest"
    package_name = "sklearn"
    unavailable_message = "scikit-learn is not installed. Install optional dependency 'scikit-learn' to enable this model."

    def __init__(self, n_estimators: int = 120, max_depth: int = 18, min_samples_leaf: int = 2) -> None:
        super().__init__()
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf

    def build_model(self):
        try:
            from sklearn.ensemble import RandomForestRegressor
        except Exception as exc:
            raise RuntimeError(self.unavailable_message) from exc
        return RandomForestRegressor(
            n_estimators=self.n_estimators,
            random_state=42,
            n_jobs=WEB_WORKER_N_JOBS,
            min_samples_leaf=self.min_samples_leaf,
            max_depth=self.max_depth,
        )
