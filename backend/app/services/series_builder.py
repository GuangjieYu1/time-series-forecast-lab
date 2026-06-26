from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel

from app.core.errors import AppError
from app.schemas import Diagnostics, ForecastRunRequest, HistoryPoint
from app.services.time_parser import detect_frequency, parse_datetime_value


PANDAS_FREQ = {
    "H": "h",
    "D": "D",
    "W": "W-MON",
    "M": "MS",
    "Q": "QS",
    "Y": "YS",
}

FREQUENCY_ORDER = ["H", "D", "W", "M", "Q", "Y"]


class TimeSeriesPoint(BaseModel):
    time: datetime
    value: float


class TimeSeriesData(BaseModel):
    targetColumn: str
    frequency: str
    points: list[TimeSeriesPoint]
    diagnostics: Diagnostics


@dataclass
class BuildResult:
    series: TimeSeriesData
    data_profile: dict[str, Any]


def _normalize_time(series: pd.Series, frequency: str) -> pd.Series:
    dt = pd.to_datetime(series)
    if frequency == "H":
        return dt.dt.floor("h")
    if frequency == "D":
        return dt.dt.floor("D")
    if frequency == "W":
        return dt.dt.to_period("W-MON").dt.start_time
    if frequency == "M":
        return dt.dt.to_period("M").dt.start_time
    if frequency == "Q":
        return dt.dt.to_period("Q").dt.start_time
    if frequency == "Y":
        return dt.dt.to_period("Y").dt.start_time
    return dt


def is_frequency_allowed(source_frequency: str, requested_frequency: str) -> bool:
    return FREQUENCY_ORDER.index(requested_frequency) >= FREQUENCY_ORDER.index(source_frequency)


def _coerce_target(df: pd.DataFrame, target_column: str, method: str) -> pd.Series:
    if method == "count":
        return pd.Series([1.0] * len(df), index=df.index)
    values = pd.to_numeric(df[target_column], errors="coerce")
    return values


def _fill_missing(series_df: pd.DataFrame, frequency: str, strategy: str) -> tuple[pd.DataFrame, int]:
    if series_df.empty or frequency not in PANDAS_FREQ:
        return series_df, 0
    full_index = pd.date_range(series_df["time"].min(), series_df["time"].max(), freq=PANDAS_FREQ[frequency])
    indexed = series_df.set_index("time").reindex(full_index)
    missing_count = int(indexed["value"].isna().sum())
    if strategy == "zero":
        indexed["value"] = indexed["value"].fillna(0)
    elif strategy == "ffill":
        indexed["value"] = indexed["value"].ffill().bfill()
    else:
        indexed = indexed.dropna(subset=["value"])
    return indexed.reset_index(names="time"), missing_count


def build_time_series(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> BuildResult:
    if request.timeColumn not in df.columns:
        raise AppError(f"Time column '{request.timeColumn}' does not exist.")
    if target_column not in df.columns and request.aggregation.method != "count":
        raise AppError(f"Target column '{target_column}' does not exist.")

    original_count = len(df)
    parsed_times = [parse_datetime_value(value) for value in df[request.timeColumn].tolist()]
    valid_mask = [item.ok and item.value is not None for item in parsed_times]
    if sum(valid_mask) == 0:
        raise AppError("No parseable time values were found in the selected time column.")

    working = df.loc[valid_mask].copy()
    working["_parsed_time"] = [item.value for item in parsed_times if item.ok and item.value is not None]

    frequency_warnings: list[str] = []
    detected_frequency, frequency_warnings = detect_frequency(working[request.timeColumn].tolist())
    if request.frequency == "auto":
        frequency = detected_frequency
    else:
        frequency = request.frequency
    if frequency not in FREQUENCY_ORDER:
        raise AppError("The selected frequency is not supported. Use H, D, W, M, Q, or Y.")
    if not is_frequency_allowed(detected_frequency, frequency):
        raise AppError(
            f"Source data frequency is {detected_frequency}; forecasting frequency {frequency} is too fine.",
            code="FREQUENCY_TOO_FINE",
            details={"detectedFrequency": detected_frequency, "requestedFrequency": frequency},
        )

    method = request.aggregation.method if request.dataMode == "raw" or request.aggregation.enabled else "mean"
    values = _coerce_target(working, target_column, method)
    working["_target_value"] = values
    if method != "count":
        working = working.dropna(subset=["_target_value"])

    valid_count = len(working)
    if valid_count < 2:
        raise AppError("Fewer than two valid time series points remain after parsing.")

    working["_bucket_time"] = _normalize_time(working["_parsed_time"], frequency)
    duplicate_time_count = int(working.duplicated("_bucket_time").sum())

    if request.dataMode == "raw" or request.aggregation.enabled:
        grouped = working.groupby("_bucket_time")["_target_value"].agg(method).reset_index()
    else:
        grouped = working.groupby("_bucket_time")["_target_value"].mean().reset_index()
    grouped.columns = ["time", "value"]
    grouped = grouped.sort_values("time")

    missing_time_count = 0
    if request.fillMissingTimeSteps:
        grouped, missing_time_count = _fill_missing(grouped, frequency, request.missingValueStrategy)
    else:
        grouped = grouped.dropna(subset=["value"])

    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce")
    grouped = grouped.dropna(subset=["value"])

    if len(grouped) < 3:
        raise AppError("Fewer than three valid time series points remain after aggregation.")

    warnings = list(frequency_warnings)
    if len(grouped) < 30:
        warnings.append("Valid time points are fewer than 30; forecast comparison may be unstable.")
    if duplicate_time_count and request.dataMode == "aggregated":
        warnings.append("Duplicate timestamps were found and averaged for the aggregated time series.")
    if missing_time_count:
        warnings.append(f"{missing_time_count} missing time steps were filled for a regular {frequency} series.")

    points = [
        TimeSeriesPoint(time=row.time.to_pydatetime() if hasattr(row.time, "to_pydatetime") else row.time, value=float(row.value))
        for row in grouped.itertuples(index=False)
    ]
    diagnostics = Diagnostics(
        originalRowCount=original_count,
        validRowCount=len(points),
        droppedRowCount=original_count - valid_count,
        duplicateTimeCount=duplicate_time_count,
        missingTimeCount=missing_time_count,
        timeStart=points[0].time.isoformat() if points else None,
        timeEnd=points[-1].time.isoformat() if points else None,
        warnings=warnings,
    )
    data_profile = {
        "mode": request.dataMode,
        "timeColumn": request.timeColumn,
        "targetColumn": target_column,
        "aggregation": method,
        "detectedFrequency": frequency,
        "sourceFrequency": detected_frequency,
        "history": [HistoryPoint(time=point.time.isoformat(), value=point.value).model_dump() for point in points],
    }
    return BuildResult(
        series=TimeSeriesData(targetColumn=target_column, frequency=frequency, points=points, diagnostics=diagnostics),
        data_profile=data_profile,
    )
