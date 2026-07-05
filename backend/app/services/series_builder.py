from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.schemas import CovariateConfig, Diagnostics, ForecastRunRequest, HistoryPoint, HolidayConfig
from app.services.covariate_flow import (
    active_model_covariate_columns,
    covariate_strategy_warnings,
    describe_covariates,
    resolve_covariate_configs,
)
from app.services.data_cleaner import clean_source_data, detect_and_handle_outliers
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES, build_holiday_features
from app.services.time_parser import detect_frequency, parse_datetime_value


PANDAS_FREQ = {"H": "h", "D": "D", "W": "W-MON", "M": "MS", "Q": "QS", "Y": "YS"}
FREQUENCY_ORDER = ["H", "D", "W", "M", "Q", "Y"]


class TimeSeriesPoint(BaseModel):
    time: datetime
    value: float


class TimeSeriesData(BaseModel):
    targetColumn: str
    frequency: str
    points: list[TimeSeriesPoint]
    diagnostics: Diagnostics
    covariateColumns: list[str] = Field(default_factory=list)
    generatedCovariateColumns: list[str] = Field(default_factory=list)
    covariateRows: list[dict[str, float]] = Field(default_factory=list)
    covariateConfigs: list[CovariateConfig] = Field(default_factory=list)
    futureCovariateTimes: list[datetime] = Field(default_factory=list)
    futureCovariateRows: list[dict[str, float]] = Field(default_factory=list)
    holidayConfig: HolidayConfig = Field(default_factory=HolidayConfig)


@dataclass
class BuildResult:
    series: TimeSeriesData
    data_profile: dict[str, Any]


def _normalize_time(series: pd.Series, frequency: str) -> pd.Series:
    dt = pd.to_datetime(series)
    if frequency == "H": return dt.dt.floor("h")
    if frequency == "D": return dt.dt.floor("D")
    if frequency == "W": return dt.dt.to_period("W-MON").dt.start_time
    if frequency == "M": return dt.dt.to_period("M").dt.start_time
    if frequency == "Q": return dt.dt.to_period("Q").dt.start_time
    if frequency == "Y": return dt.dt.to_period("Y").dt.start_time
    return dt


def is_frequency_allowed(source_frequency: str, requested_frequency: str) -> bool:
    return FREQUENCY_ORDER.index(requested_frequency) >= FREQUENCY_ORDER.index(source_frequency)


def _fill_frame(frame: pd.DataFrame, columns: list[str], strategy: str, limit: int | None) -> pd.DataFrame:
    result = frame.copy()
    if strategy == "zero": result[columns] = result[columns].fillna(0.0)
    elif strategy == "ffill": result[columns] = result[columns].ffill().bfill()
    elif strategy == "bfill": result[columns] = result[columns].bfill().ffill()
    elif strategy == "median": result[columns] = result[columns].fillna(result[columns].median()).fillna(0.0)
    elif strategy in {"interpolate", "time"}:
        if strategy == "time" and "time" in result.columns:
            indexed = result.set_index("time")
            indexed[columns] = indexed[columns].interpolate(method="time", limit=limit, limit_direction="both")
            result = indexed.reset_index()
        else:
            result[columns] = result[columns].interpolate(method="linear", limit=limit, limit_direction="both")
    return result


def _fill_missing(series_df: pd.DataFrame, frequency: str, strategy: str, fill_missing_steps: bool, fill_columns: list[str], limit: int | None) -> tuple[pd.DataFrame, int, int]:
    if series_df.empty or frequency not in PANDAS_FREQ:
        return series_df, 0, 0
    full_index = pd.date_range(series_df["time"].min(), series_df["time"].max(), freq=PANDAS_FREQ[frequency])
    indexed = series_df.set_index("time").reindex(full_index).reset_index(names="time")
    missing_count = int(indexed["value"].isna().sum())
    if not fill_missing_steps:
        return series_df, missing_count, 0
    feature_columns = [column for column in fill_columns if column in indexed.columns]
    if strategy == "drop":
        indexed = indexed.dropna(subset=["value"])
    else:
        indexed = _fill_frame(indexed, feature_columns, strategy, limit)
        indexed = indexed.dropna(subset=["value"])
    filled_count = max(0, missing_count - int(indexed["value"].isna().sum())) if strategy != "drop" else 0
    return indexed, missing_count, filled_count


def _coerce_covariate_series(series: pd.Series, normalize_thousands: bool = True) -> pd.Series:
    values: list[float] = []
    truthy, falsy = {"true", "yes", "y", "1", "on"}, {"false", "no", "n", "0", "off"}
    for value in series.tolist():
        if pd.isna(value): values.append(float("nan")); continue
        if isinstance(value, bool): values.append(1.0 if value else 0.0); continue
        text = str(value).strip()
        if normalize_thousands: text = text.replace(",", "")
        lowered = text.lower()
        if lowered in truthy: values.append(1.0); continue
        if lowered in falsy: values.append(0.0); continue
        try: values.append(float(text))
        except (TypeError, ValueError): values.append(float("nan"))
    return pd.Series(values, index=series.index, dtype=float)


def _resolve_covariate_columns(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> list[str]:
    resolved, seen = [], set()
    for column in request.covariateColumns:
        if column in seen or column in {request.timeColumn, target_column}: continue
        if column not in df.columns: raise AppError(f"Covariate column '{column}' does not exist.")
        resolved.append(column); seen.add(column)
    configured_unknown = [item.column for item in request.covariateConfigs if item.column not in resolved]
    if configured_unknown:
        raise AppError(f"Covariate configuration references unselected columns: {', '.join(configured_unknown)}")
    return resolved


def _future_source_rows(df: pd.DataFrame, request: ForecastRunRequest, target_column: str, history_end: datetime, frequency: str, columns: list[str]) -> tuple[list[datetime], list[dict[str, float]]]:
    if not columns or target_column not in df.columns:
        return [], []
    parsed = [parse_datetime_value(value) for value in df[request.timeColumn].tolist()]
    rows: list[dict[str, Any]] = []
    for position, item in enumerate(parsed):
        if not item.ok or item.value is None or item.value <= history_end: continue
        target_value = df.iloc[position][target_column]
        if pd.notna(target_value) and str(target_value).strip() != "": continue
        row = {"time": item.value}
        for column in columns:
            row[column] = _coerce_covariate_series(pd.Series([df.iloc[position][column]])).iloc[0]
        rows.append(row)
    if not rows:
        return [], []
    frame = pd.DataFrame(rows)
    frame["time"] = _normalize_time(frame["time"], frequency)
    frame = frame.groupby("time", sort=True)[columns].mean().reset_index()
    times = [value.to_pydatetime() if hasattr(value, "to_pydatetime") else value for value in frame["time"]]
    values = [{column: float(value) if pd.notna(value) else float("nan") for column, value in row.items()} for row in frame[columns].to_dict(orient="records")]
    return times, values


def build_time_series(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> BuildResult:
    if request.timeColumn not in df.columns: raise AppError(f"Time column '{request.timeColumn}' does not exist.")
    if target_column not in df.columns and request.aggregation.method != "count": raise AppError(f"Target column '{target_column}' does not exist.")
    cleaning = request.cleaningConfig
    assert cleaning is not None
    user_covariates = _resolve_covariate_columns(df, request, target_column)
    all_configs = resolve_covariate_configs(user_covariates, request.covariateConfigs)
    active_user_covariates = active_model_covariate_columns(user_covariates, all_configs)

    original_count = len(df)
    method = request.aggregation.method if request.dataMode == "raw" or request.aggregation.enabled else cleaning.duplicateTimeStrategy
    cleaned = clean_source_data(
        df, request.timeColumn, target_column, count_mode=method == "count",
        missing_strategy=cleaning.missingValueStrategy, trim_strings=cleaning.trimStrings,
        invalid_time_strategy=cleaning.invalidTimeStrategy,
        normalize_thousands_separators=cleaning.normalizeThousandsSeparators,
        sort_by_time=cleaning.sortByTime, interpolation_limit=cleaning.interpolationLimit,
    )
    working = cleaned.frame
    if working.empty:
        if cleaned.invalid_time_count == original_count: raise AppError("No parseable time values were found in the selected time column.")
        raise AppError("No valid target values remain after data cleaning.")

    detected_frequency, frequency_warnings = detect_frequency(working[request.timeColumn].tolist())
    frequency = detected_frequency if request.frequency == "auto" else request.frequency
    if frequency not in FREQUENCY_ORDER: raise AppError("The selected frequency is not supported. Use H, D, W, M, Q, or Y.")
    if not is_frequency_allowed(detected_frequency, frequency):
        raise AppError(f"Source data frequency is {detected_frequency}; forecasting frequency {frequency} is too fine.", code="FREQUENCY_TOO_FINE")
    if len(working) < 2: raise AppError("Fewer than two valid time series points remain after parsing.")

    working["_bucket_time"] = _normalize_time(working["_parsed_time"], frequency)
    duplicate_time_count = int(working.duplicated("_bucket_time").sum())
    for column in active_user_covariates:
        working[f"_covariate_{column}"] = _coerce_covariate_series(working[column], cleaning.normalizeThousandsSeparators)
    aggregation = method if request.dataMode == "raw" or request.aggregation.enabled else cleaning.duplicateTimeStrategy
    grouped = working.groupby("_bucket_time", sort=True)["_target_value"].agg(aggregation).reset_index()
    grouped.columns = ["time", "value"]
    if active_user_covariates:
        source_columns = [f"_covariate_{column}" for column in active_user_covariates]
        covariate_frame = working.groupby("_bucket_time", sort=True)[source_columns].mean().reset_index().rename(columns={"_bucket_time": "time", **{f"_covariate_{column}": column for column in active_user_covariates}})
        grouped = grouped.merge(covariate_frame, on="time", how="left")
    grouped = grouped.sort_values("time")
    grouped, missing_time_count, filled_gap_count = _fill_missing(grouped, frequency, cleaning.missingValueStrategy, cleaning.fillMissingTimeSteps, ["value", *active_user_covariates], cleaning.interpolationLimit)

    covariate_missing_count = int(grouped[active_user_covariates].isna().sum().sum()) if active_user_covariates else 0
    config_by_column = {item.column: item for item in all_configs}
    for column in active_user_covariates:
        grouped = _fill_frame(grouped, [column], config_by_column[column].missingValueStrategy, cleaning.interpolationLimit)
        grouped[column] = grouped[column].ffill().bfill().fillna(0.0)

    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce")
    grouped = grouped.dropna(subset=["value"])
    grouped, outlier_count, outlier_adjusted_count = detect_and_handle_outliers(grouped, cleaning.outlierStrategy, cleaning.outlierIqrMultiplier, cleaning.hampelWindow, cleaning.hampelSigma)
    if len(grouped) < 3: raise AppError("Fewer than three valid time series points remain after aggregation.")

    normalized_times = [value.to_pydatetime() if hasattr(value, "to_pydatetime") else value for value in grouped["time"]]
    holiday_result = build_holiday_features(normalized_times, frequency, request.holidayConfig) if request.featureConfig.holidayFeatures and request.holidayConfig.enabled else None
    holiday_columns: list[str] = []
    if holiday_result and holiday_result.names:
        holiday_columns = holiday_result.names
        for index, column in enumerate(holiday_result.names): grouped[column] = holiday_result.matrix[:, index]
    model_covariates = [*active_user_covariates, *holiday_columns]

    history_end = normalized_times[-1]
    future_times, future_rows = _future_source_rows(df, request, target_column, history_end, frequency, active_user_covariates)
    warnings = list(frequency_warnings) + covariate_strategy_warnings(user_covariates, all_configs)
    if len(grouped) < 30: warnings.append("有效时间点少于 30 个，预测比较可能不稳定。")
    if duplicate_time_count and request.dataMode == "aggregated": warnings.append(f"Duplicate timestamps were found and resolved with {cleaning.duplicateTimeStrategy}.")
    if missing_time_count: warnings.append(f"检测到 {missing_time_count} 个缺失时间点。")
    if covariate_missing_count: warnings.append(f"已按逐列策略处理 {covariate_missing_count} 个协变量缺失值。")
    if outlier_count: warnings.append(f"检测到 {outlier_count} 个异常值，调整 {outlier_adjusted_count} 个。")

    points = [TimeSeriesPoint(time=row.time.to_pydatetime() if hasattr(row.time, "to_pydatetime") else row.time, value=float(row.value)) for row in grouped.itertuples(index=False)]
    covariate_rows = [{column: float(value) for column, value in row.items()} for row in grouped[model_covariates].to_dict(orient="records")] if model_covariates else []
    diagnostics = Diagnostics(
        originalRowCount=original_count, validRowCount=len(points), droppedRowCount=cleaned.dropped_source_row_count,
        duplicateTimeCount=duplicate_time_count, missingTimeCount=missing_time_count, invalidTimeCount=cleaned.invalid_time_count,
        inputMissingTargetCount=cleaned.input_missing_target_count, invalidTargetCount=cleaned.invalid_target_count,
        filledValueCount=cleaned.filled_target_count + filled_gap_count, outlierCount=outlier_count,
        outlierAdjustedCount=outlier_adjusted_count, cleaningActions=cleaned.actions,
        timeStart=points[0].time.isoformat(), timeEnd=points[-1].time.isoformat(), warnings=warnings,
    )
    data_profile = {
        "mode": request.dataMode, "timeColumn": request.timeColumn, "targetColumn": target_column,
        "covariateColumns": user_covariates, "modelCovariateColumns": model_covariates,
        "covariates": describe_covariates(user_covariates, all_configs),
        "covariateConfigs": [item.model_dump() for item in all_configs],
        "holidayConfig": request.holidayConfig.model_dump(),
        "holidayMarkers": [item.model_dump() for item in (holiday_result.markers if holiday_result else [])],
        "featureConfig": request.featureConfig.model_dump(), "aggregation": aggregation,
        "detectedFrequency": frequency, "sourceFrequency": detected_frequency, "rawColumnCount": len(df.columns),
        "cleaning": cleaning.model_dump(), "warnings": warnings, "originalRowCount": original_count,
        "validPointCount": len(points), "history": [HistoryPoint(time=point.time.isoformat(), value=point.value).model_dump() for point in points],
        "covariateHistory": [{"time": point.time.isoformat(), **row} for point, row in zip(points, covariate_rows)],
        "futureCovariates": [{"time": value.isoformat(), **row} for value, row in zip(future_times, future_rows)],
    }
    return BuildResult(
        series=TimeSeriesData(targetColumn=target_column, frequency=frequency, points=points, diagnostics=diagnostics,
            covariateColumns=active_user_covariates, generatedCovariateColumns=holiday_columns, covariateRows=covariate_rows, covariateConfigs=all_configs,
            futureCovariateTimes=future_times, futureCovariateRows=future_rows, holidayConfig=request.holidayConfig),
        data_profile=data_profile,
    )