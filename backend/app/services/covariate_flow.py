from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import numpy as np

from app.core.errors import AppError
from app.schemas import CovariateConfig, HolidayConfig
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES, holiday_row


_KNOWN_FUTURE_ALIAS_MAP: dict[str, str] = {
    "weekday": "weekday",
    "dayofweek": "weekday",
    "dayweek": "weekday",
    "month": "month",
    "quarter": "quarter",
    "weekend": "weekend",
    "isweekend": "weekend",
    "workday": "workday",
    "isworkday": "workday",
    "businessday": "workday",
    "holiday": "holiday",
    "isholiday": "holiday",
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
    if config.type == "known_future":
        forecast_strategy = "calendar" if canonical else "use_future_rows"
        backtest_strategy = "use_test_timeline"
        leakage_risk = False
        used_during = ["training", "backtest", "forecast"]
        note = (
            f"{name} 按未来已知协变量（Known Future Covariate）处理，回测使用测试时间轴，最终预测使用未来时间轴。"
            if canonical
            else f"{name} 按未来已知协变量（Known Future Covariate）处理，回测与最终预测都读取用户提供的未来行。"
        )
    else:
        forecast_strategy = "repeat_last_known"
        backtest_strategy = config.backtestStrategy
        leakage_risk = backtest_strategy == "use_test_values"
        used_during = ["training", "backtest", "forecast"]
        if backtest_strategy == "historical_mean":
            note = f"{name} 按静态协变量处理：训练与预测重复最后一个已知值，回测阶段用训练段历史均值展开整个 horizon。"
        elif backtest_strategy == "use_test_values":
            note = f"{name} 按静态协变量处理：最终预测仍重复最后一个已知值；当前回测会读取测试段真实协变量值，存在未来信息泄漏风险。"
        else:
            note = f"{name} 按静态协变量（Static Covariate）处理，训练、回测与预测默认重复最后一个已知值。"
    return {
        "name": name,
        "type": config.type,
        "generator": "Covariate Loader",
        "forecastStrategy": forecast_strategy,
        "backtestStrategy": backtest_strategy,
        "usedDuring": used_during,
        "leakageRisk": leakage_risk,
        "note": note,
    }


def describe_covariates(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[dict[str, Any]]:
    resolved = {item.column: item for item in resolve_covariate_configs(columns, configs)}
    return [classify_covariate(column, resolved[column]) for column in columns]


def active_model_covariate_columns(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[str]:
    resolved = {item.column: item for item in resolve_covariate_configs(columns, configs)}
    return [column for column in columns if resolved[column].type in {"known_future", "static"}]


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
    purpose: Literal["backtest", "forecast"] = "forecast",
) -> list[dict[str, float]] | None:
    del history_times, primary_model_id, primary_model_parameters
    if not covariate_columns:
        return None
    history_rows = history_rows or []
    observed_future_rows = observed_future_rows or []
    resolved = {item.column: item for item in resolve_covariate_configs(covariate_columns, covariate_configs)}
    fallback_row = history_rows[-1] if history_rows else {}
    historical_means = {column: _historical_mean(history_rows, column) for column in covariate_columns}

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
            else:
                value = _static_covariate_value(
                    column=column,
                    config=config,
                    purpose=purpose,
                    fallback_row=fallback_row,
                    observed_row=observed_row,
                    historical_mean=historical_means.get(column),
                )
            if value is None:
                value = 0.0
            next_row[column] = float(value)
        rows.append(next_row)
    return rows


def covariate_strategy_warnings(columns: list[str], configs: list[CovariateConfig] | None = None) -> list[str]:
    return [item["note"] for item in describe_covariates(columns, configs) if item.get("note")]


def _static_covariate_value(
    *,
    column: str,
    config: CovariateConfig,
    purpose: Literal["backtest", "forecast"],
    fallback_row: dict[str, float],
    observed_row: dict[str, float],
    historical_mean: float | None,
) -> float | None:
    if purpose == "backtest":
        if config.backtestStrategy == "use_test_values":
            candidate = _safe_float(observed_row.get(column))
            if candidate is not None:
                return candidate
        if config.backtestStrategy == "historical_mean" and historical_mean is not None:
            return historical_mean
    return _safe_float(fallback_row.get(column))


def _historical_mean(rows: list[dict[str, float]], column: str) -> float | None:
    values = [_safe_float(row.get(column)) for row in rows]
    numeric_values = [float(value) for value in values if value is not None and np.isfinite(value)]
    if not numeric_values:
        return None
    return float(np.mean(np.asarray(numeric_values, dtype=float)))


def _generate_known_future_value(column: str, value_time: datetime) -> float | None:
    canonical = canonical_covariate_name(column)
    if canonical == "weekday":
        return float(value_time.weekday())
    if canonical == "month":
        return float(value_time.month)
    if canonical == "quarter":
        return float(((value_time.month - 1) // 3) + 1)
    if canonical == "weekend":
        return 1.0 if value_time.weekday() >= 5 else 0.0
    if canonical == "workday":
        return 1.0 if value_time.weekday() < 5 else 0.0
    if canonical == "holiday":
        return 1.0 if value_time.weekday() >= 5 else 0.0
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None
