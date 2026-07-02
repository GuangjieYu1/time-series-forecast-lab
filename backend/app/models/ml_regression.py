from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.core.constants import DEFAULT_RANDOM_SEED
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
DEFAULT_FEATURE_CONFIG = {
    "lagFeatures": True,
    "rollingFeatures": True,
    "calendarFeatures": True,
    "covariates": True,
}


class LagFeatureRegressor:
    model_id = "lag_feature_regressor"
    package_name = ""
    unavailable_message = "Regression package is not installed."

    def __init__(self) -> None:
        self.model: Any = None
        self.times: list[datetime] = []
        self.values: list[float] = []
        self.frequency = "D"
        self.feature_config = dict(DEFAULT_FEATURE_CONFIG)
        self.feature_columns: list[str] = []
        self.covariate_columns: list[str] = []
        self.covariate_history: list[dict[str, float]] = []
        self.residual_scale = 0.0
        self.warnings: list[str] = []

    def build_model(self):
        raise NotImplementedError

    def _normalize_feature_config(self, feature_config: dict[str, bool] | None) -> dict[str, bool]:
        normalized = dict(DEFAULT_FEATURE_CONFIG)
        if feature_config:
            for key in normalized:
                if key in feature_config:
                    normalized[key] = bool(feature_config[key])
        return normalized

    def _uses_covariates(self) -> bool:
        return self.feature_config["covariates"] and bool(self.covariate_columns)

    def _ensure_feature_columns(self) -> None:
        columns: list[str] = []
        if self.feature_config["lagFeatures"]:
            columns.extend(["lag_1", "lag_2", "lag_3", "lag_7"])
        if self.feature_config["rollingFeatures"]:
            columns.extend(["rolling_mean_3", "rolling_mean_7", "rolling_std_7"])
        if self.feature_config["calendarFeatures"]:
            columns.extend(["time_index", "day_of_week", "month"])
        if self._uses_covariates():
            columns.extend(self.covariate_columns)
        if not columns:
            raise RuntimeError("At least one feature family must be enabled for regression models.")
        self.feature_columns = columns

    def _feature_summary(self) -> str:
        labels: list[str] = []
        if self.feature_config["lagFeatures"]:
            labels.append("lag 特征")
        if self.feature_config["rollingFeatures"]:
            labels.append("滚动统计")
        if self.feature_config["calendarFeatures"]:
            labels.append("日历/趋势特征")
        if self._uses_covariates():
            labels.append(f"{len(self.covariate_columns)} 个用户协变量")
        return "、".join(labels)

    def _normalize_covariate_rows(
        self,
        covariates: list[dict[str, float]] | None,
        *,
        initialize_columns: bool,
    ) -> list[dict[str, float]]:
        if not covariates:
            return []
        if initialize_columns:
            self.covariate_columns = [str(column) for column in covariates[0].keys()]
        normalized_rows: list[dict[str, float]] = []
        for row in covariates:
            normalized_rows.append({column: float(row.get(column, 0.0)) for column in self.covariate_columns})
        return normalized_rows

    def _features_for(
        self,
        values: list[float],
        target_time: datetime,
        time_index: int,
        covariate_row: dict[str, float] | None = None,
    ) -> list[float]:
        series = [float(value) for value in values]

        def lag(offset: int) -> float:
            if len(series) >= offset:
                return series[-offset]
            return series[-1]

        last_3 = series[-3:] if len(series) >= 3 else series
        last_7 = series[-7:] if len(series) >= 7 else series
        rolling_std = float(np.std(np.asarray(last_7, dtype=float), ddof=0)) if len(last_7) > 1 else 0.0
        features: list[float] = []
        if self.feature_config["lagFeatures"]:
            features.extend([lag(1), lag(2), lag(3), lag(7)])
        if self.feature_config["rollingFeatures"]:
            features.extend([float(np.mean(last_3)), float(np.mean(last_7)), rolling_std])
        if self.feature_config["calendarFeatures"]:
            features.extend([float(time_index), float(target_time.weekday()), float(target_time.month)])
        if self._uses_covariates():
            row = covariate_row or {}
            features.extend(float(row.get(column, 0.0)) for column in self.covariate_columns)
        return features

    def _warmup_steps(self) -> int:
        return 7 if (self.feature_config["lagFeatures"] or self.feature_config["rollingFeatures"]) else 1

    def _training_matrix(self) -> tuple[np.ndarray, np.ndarray]:
        minimum_required = 14 if self._warmup_steps() >= 7 else 8
        if len(self.values) < minimum_required:
            raise RuntimeError(f"At least {minimum_required} training points are required for regression feature models.")
        rows: list[list[float]] = []
        targets: list[float] = []
        start_index = self._warmup_steps()
        for index in range(start_index, len(self.values)):
            history = self.values[:index]
            covariate_row = self.covariate_history[index] if self._uses_covariates() else None
            rows.append(self._features_for(history, self.times[index], index, covariate_row))
            targets.append(self.values[index])
        return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float)

    def fit(
        self,
        times: list[datetime],
        values: list[float],
        frequency: str,
        covariates: list[dict[str, float]] | None = None,
        feature_config: dict[str, bool] | None = None,
    ) -> None:
        self.times = list(times)
        self.values = [float(value) for value in values]
        self.frequency = frequency
        self.feature_config = self._normalize_feature_config(feature_config)
        self.covariate_history = self._normalize_covariate_rows(covariates, initialize_columns=True)
        if self.covariate_history and len(self.covariate_history) != len(self.values):
            raise RuntimeError("Covariate rows must align one-to-one with the training history.")
        if not self.covariate_history:
            self.covariate_columns = []
        self._ensure_feature_columns()
        self.warnings = [f"机器学习模型使用 {self._feature_summary()} 进行递归多步预测。"]
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

    def predict(self, horizon: int, future_covariates: list[dict[str, float]] | None = None) -> ForecastOutput:
        if self.model is None:
            raise RuntimeError("Model was not fitted.")
        history = list(self.values)
        predictions: list[float] = []
        lower: list[float | None] = []
        upper: list[float | None] = []
        future_times = self._future_times(horizon)
        warnings = list(self.warnings)
        normalized_future_covariates = self._normalize_covariate_rows(future_covariates, initialize_columns=False)
        if self._uses_covariates() and normalized_future_covariates and len(normalized_future_covariates) < horizon:
            raise RuntimeError("Future covariate rows are fewer than the requested forecast horizon.")
        covariate_fallback = self.covariate_history[-1] if self._uses_covariates() and self.covariate_history else None
        if self._uses_covariates() and not normalized_future_covariates and covariate_fallback:
            warnings.append("未来协变量未提供，已回退为重复最后一条已知协变量快照。")
        for step, future_time in enumerate(future_times):
            covariate_row = None
            if self._uses_covariates():
                if normalized_future_covariates:
                    covariate_row = normalized_future_covariates[step]
                else:
                    covariate_row = covariate_fallback
            features = pd.DataFrame(
                [self._features_for(history, future_time, len(history) + step, covariate_row)],
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
        return ForecastOutput(predictions=predictions, lower=lower, upper=upper, warnings=warnings)


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
            random_state=DEFAULT_RANDOM_SEED,
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
            random_state=DEFAULT_RANDOM_SEED,
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
            random_state=DEFAULT_RANDOM_SEED,
            n_jobs=WEB_WORKER_N_JOBS,
            min_samples_leaf=self.min_samples_leaf,
            max_depth=self.max_depth,
        )
