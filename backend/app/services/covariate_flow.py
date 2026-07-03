from __future__ import annotations

from datetime import datetime
from typing import Any, Literal


CovariateType = Literal["known_future", "static"]
CovariateStrategy = Literal["calendar", "repeat_last_known", "use_test_timeline"]

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


def classify_covariate(name: str) -> dict[str, Any]:
    canonical = canonical_covariate_name(name)
    covariate_type: CovariateType = "known_future" if canonical else "static"
    forecast_strategy: CovariateStrategy = "calendar" if canonical else "repeat_last_known"
    backtest_strategy: CovariateStrategy = "use_test_timeline" if canonical else "repeat_last_known"
    note = None
    if covariate_type == "static":
        note = (
            f"{name} 当前按 Static Covariate 处理。Backtest 和 Forecast 都只会重复最后一个已知值，"
            "不会读取测试集真实未来值。"
        )
    elif canonical == "holiday":
        note = (
            f"{name} 被归类为 Known Future Covariate。若未来没有明确节假日表，Forecast 会先尝试使用日历代理值；"
            "如无法可靠生成，将退回最后一个已知值。"
        )
    return {
        "name": name,
        "type": covariate_type,
        "generator": "Covariate Loader",
        "forecastStrategy": forecast_strategy,
        "backtestStrategy": backtest_strategy,
        "usedDuring": ["training", "backtest", "forecast"],
        "note": note,
    }


def describe_covariates(columns: list[str]) -> list[dict[str, Any]]:
    return [classify_covariate(column) for column in columns]


def build_future_covariate_rows(
    *,
    covariate_columns: list[str],
    history_rows: list[dict[str, float]] | None,
    observed_future_rows: list[dict[str, float]] | None,
    future_times: list[datetime],
) -> list[dict[str, float]] | None:
    if not covariate_columns:
        return None
    history_rows = history_rows or []
    observed_future_rows = observed_future_rows or []
    descriptors = {item["name"]: item for item in describe_covariates(covariate_columns)}
    fallback_row = history_rows[-1] if history_rows else {}

    rows: list[dict[str, float]] = []
    for index, future_time in enumerate(future_times):
        observed_row = observed_future_rows[index] if index < len(observed_future_rows) else {}
        next_row: dict[str, float] = {}
        for column in covariate_columns:
            descriptor = descriptors[column]
            value = None
            if descriptor["type"] == "known_future":
                value = _generate_known_future_value(column, future_time)
                if value is None:
                    value = _safe_float(observed_row.get(column))
            if value is None:
                value = _safe_float(fallback_row.get(column))
            if value is None:
                value = 0.0
            next_row[column] = float(value)
        rows.append(next_row)
    return rows


def covariate_strategy_warnings(columns: list[str]) -> list[str]:
    warnings: list[str] = []
    for descriptor in describe_covariates(columns):
        note = descriptor.get("note")
        if isinstance(note, str) and note:
            warnings.append(note)
    return warnings


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
        return float(value)
    except (TypeError, ValueError):
        return None
