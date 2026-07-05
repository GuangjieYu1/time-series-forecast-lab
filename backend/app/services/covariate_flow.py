from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from app.core.errors import AppError
from app.schemas import CovariateConfig, HolidayConfig
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES, holiday_row


_KNOWN_FUTURE_ALIAS_MAP: dict[str, str] = {
    "weekday": "weekday", "dayofweek": "weekday", "dayweek": "weekday",
    "month": "month", "quarter": "quarter", "weekend": "weekend",
    "isweekend": "weekend", "workday": "workday", "isworkday": "workday",
    "businessday": "workday", "holiday": "holiday", "isholiday": "holiday",
}


def normalize_covariate_name(name: str) -> str:
    lowered = str(name).strip().lower()
    return "".join(character for character in lowered if character.isalnum())


def canonical_covariate_name(name: str) -> str | None:
    return _KNOWN_FUTURE_ALIAS_MAP.get(normalize_covariate_name(name))


def resolve_covariate_configs(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[CovariateConfig]:
    configured = {item.column: item for item in configs or []}
    resolved: list[CovariateConfig] = []
    for column in columns:
        if column in configured:
            resolved.append(configured[column])
        else:
            resolved.append(CovariateConfig(column=column, type="known_future" if canonical_covariate_name(column) else "static"))
    return resolved


def classify_covariate(name: str, config: CovariateConfig | None = None) -> dict[str, Any]:
    config = config or CovariateConfig(column=name, type="known_future" if canonical_covariate_name(name) else "static")
    canonical = canonical_covariate_name(name)
    if config.type == "static":
        forecast_strategy = backtest_strategy = "repeat_last_known"
        used_during = ["training", "backtest", "forecast"]
        note = f"{name} 按静态协变量（Static Covariate）处理，回测与预测均重复最后一个已知值。"
    elif config.type == "unknown_future" and config.unknownFutureAction == "analysis_only":
        forecast_strategy = backtest_strategy = "drop_for_leakage"
        used_during = ["training"]
        note = f"{name} 的未来值未知，仅用于分析并在模型矩阵前丢弃，避免数据泄漏。"
    elif config.type == "unknown_future":
        forecast_strategy = backtest_strategy = "forecast_auxiliary"
        used_during = ["training", "backtest", "forecast"]
        note = f"{name} 将先按 {config.forecastMode} 策略预测，再送入主模型。"
    else:
        forecast_strategy = "calendar" if canonical else "use_future_rows"
        backtest_strategy = "use_test_timeline"
        used_during = ["training", "backtest", "forecast"]
        note = f"{name} 按未来已知协变量（Known Future Covariate）处理。" + ("最终预测读取同一 Sheet 的未来空目标行。" if not canonical else "由日历确定性生成。")
    return {
        "name": name,
        "type": config.type,
        "generator": "Covariate Loader",
        "forecastStrategy": forecast_strategy,
        "backtestStrategy": backtest_strategy,
        "usedDuring": used_during,
        "forecastMode": config.forecastMode if config.type == "unknown_future" and config.unknownFutureAction == "forecast" else None,
        "forecastModelId": config.manualModelId,
        "note": note,
    }


def describe_covariates(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[dict[str, Any]]:
    resolved = {item.column: item for item in resolve_covariate_configs(columns, configs)}
    return [classify_covariate(column, resolved[column]) for column in columns]


def active_model_covariate_columns(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[str]:
    resolved = {item.column: item for item in resolve_covariate_configs(columns, configs)}
    return [
        column for column in columns
        if not (resolved[column].type == "unknown_future" and resolved[column].unknownFutureAction == "analysis_only")
    ]


def build_future_covariate_rows(
    *,
    covariate_columns: list[str],
    history_rows: list[dict[str, float]] | None,
    observed_future_rows: list[dict[str, float]] | None,
    future_times: list[datetime],
    history_times: list[datetime] | None = None,
    covariate_configs: list[CovariateConfig] | None = None,
    frequency: str = "D",
    primary_model_id: str | None = None,
    primary_model_parameters: dict[str, Any] | None = None,
    holiday_config: HolidayConfig | None = None,
) -> list[dict[str, float]] | None:
    if not covariate_columns:
        return None
    history_rows = history_rows or []
    observed_future_rows = observed_future_rows or []
    resolved = {item.column: item for item in resolve_covariate_configs(covariate_columns, covariate_configs)}
    fallback_row = history_rows[-1] if history_rows else {}
    predicted: dict[str, list[float]] = {}

    for column in covariate_columns:
        config = resolved[column]
        if config.type != "unknown_future" or config.unknownFutureAction != "forecast":
            continue
        values = [_safe_float(row.get(column)) for row in history_rows]
        numeric_values = [float(value) for value in values if value is not None and np.isfinite(value)]
        if len(numeric_values) < 3:
            raise AppError(f"未来未知协变量 {column} 的有效历史值少于 3 个，无法预测。", code="COVARIATE_FORECAST_TOO_SHORT")
        times = list(history_times or [])
        if len(times) != len(values):
            times = future_times[:0]
        model_id = _resolve_forecast_model(config, primary_model_id, times, numeric_values, frequency)
        predicted[column] = _forecast_values(model_id, times, numeric_values, frequency, len(future_times), primary_model_parameters if config.forecastMode == "per_primary_model" else None)

    rows: list[dict[str, float]] = []
    holiday_config = holiday_config or HolidayConfig()
    for index, future_time in enumerate(future_times):
        observed_row = observed_future_rows[index] if index < len(observed_future_rows) else {}
        generated_holiday = holiday_row(future_time, frequency, holiday_config) if holiday_config.enabled else {}
        next_row: dict[str, float] = {}
        for column in covariate_columns:
            config = resolved[column]
            value = None
            if column in HOLIDAY_FEATURE_NAMES:
                value = generated_holiday.get(column)
            elif config.type == "known_future":
                value = generated_holiday.get("holiday_is_period") if canonical_covariate_name(column) == "holiday" else _generate_known_future_value(column, future_time)
                if value is None:
                    value = _safe_float(observed_row.get(column))
                    if value is None:
                        raise AppError(
                            f"未来已知协变量 {column} 在预测区间缺少第 {index + 1} 个值，请在同一 Sheet 的未来空目标行中补齐。",
                            code="KNOWN_FUTURE_VALUES_MISSING",
                            details={"column": column, "step": index + 1},
                        )
            elif config.type == "unknown_future" and config.unknownFutureAction == "forecast":
                value = predicted[column][index]
            else:
                value = _safe_float(fallback_row.get(column))
            if value is None:
                value = 0.0
            next_row[column] = float(value)
        rows.append(next_row)
    return rows


def covariate_strategy_warnings(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[str]:
    return [item["note"] for item in describe_covariates(columns, configs) if item.get("note")]


def _resolve_forecast_model(config: CovariateConfig, primary_model_id: str | None, times: list[datetime], values: list[float], frequency: str) -> str:
    if config.forecastMode == "manual":
        if not config.manualModelId:
            raise AppError(f"协变量 {config.column} 选择了手动预测，但没有指定模型。", code="COVARIATE_MODEL_REQUIRED")
        return config.manualModelId
    if config.forecastMode == "per_primary_model":
        if not primary_model_id:
            raise AppError("逐主模型协变量预测缺少主模型 ID。", code="PRIMARY_MODEL_REQUIRED")
        return primary_model_id
    candidates = ["naive", "seasonal_naive", "ets"]
    if len(values) < 10 or len(times) != len(values):
        return "naive"
    holdout = min(7, max(1, len(values) // 5))
    best_model = "naive"
    best_mae = float("inf")
    for model_id in candidates:
        try:
            predictions = _forecast_values(model_id, times[:-holdout], values[:-holdout], frequency, holdout, None)
            mae = float(np.mean(np.abs(np.asarray(values[-holdout:]) - np.asarray(predictions))))
            if mae < best_mae:
                best_mae, best_model = mae, model_id
        except Exception:
            continue
    return best_model


def _forecast_values(model_id: str, times: list[datetime], values: list[float], frequency: str, horizon: int, parameters: dict[str, Any] | None) -> list[float]:
    from app.services.model_executor import fit_model_instance, predict_model_instance
    from app.services.model_registry import create_model

    if len(times) != len(values):
        base = datetime(2000, 1, 1)
        times = [base.replace(day=1) for _ in values]
        if len(values) > 1:
            import pandas as pd
            times = [item.to_pydatetime() for item in pd.date_range(base, periods=len(values), freq="D")]
    model = create_model(model_id, parameters)
    fit_model_instance(model_id, model, times, values, frequency, feature_config={"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "holidayFeatures": False, "covariates": False})
    output = predict_model_instance(model_id, model, horizon)
    result = [float(value) for value in output.predictions[:horizon]]
    if len(result) != horizon or any(not np.isfinite(value) for value in result):
        raise RuntimeError(f"{model_id} 未返回完整且有效的协变量预测。")
    return result


def _generate_known_future_value(column: str, value_time: datetime) -> float | None:
    canonical = canonical_covariate_name(column)
    if canonical == "weekday": return float(value_time.weekday())
    if canonical == "month": return float(value_time.month)
    if canonical == "quarter": return float(((value_time.month - 1) // 3) + 1)
    if canonical == "weekend": return 1.0 if value_time.weekday() >= 5 else 0.0
    if canonical == "workday": return 1.0 if value_time.weekday() < 5 else 0.0
    if canonical == "holiday": return 1.0 if value_time.weekday() >= 5 else 0.0
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None