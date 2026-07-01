from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel

from app.core.errors import AppError
from app.schemas import Diagnostics, ForecastRunRequest, HistoryPoint
from app.services.data_cleaner import clean_source_data, detect_and_handle_outliers
from app.services.time_parser import detect_frequency


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


def _fill_missing(
    series_df: pd.DataFrame,
    frequency: str,
    strategy: str,
    fill_missing_steps: bool,
) -> tuple[pd.DataFrame, int, int]:
    if series_df.empty or frequency not in PANDAS_FREQ:
        return series_df, 0, 0
    full_index = pd.date_range(series_df["time"].min(), series_df["time"].max(), freq=PANDAS_FREQ[frequency])
    indexed = series_df.set_index("time").reindex(full_index)
    missing_count = int(indexed["value"].isna().sum())
    if not fill_missing_steps:
        return series_df, missing_count, 0
    if strategy == "zero":
        indexed["value"] = indexed["value"].fillna(0)
    elif strategy == "ffill":
        indexed["value"] = indexed["value"].ffill().bfill()
    elif strategy == "interpolate":
        indexed["value"] = indexed["value"].interpolate(method="linear", limit_direction="both")
    else:
        indexed = indexed.dropna(subset=["value"])
    filled_count = missing_count if strategy != "drop" else 0
    return indexed.reset_index(names="time"), missing_count, filled_count


def build_time_series(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> BuildResult:
    if request.timeColumn not in df.columns:
        raise AppError(f"Time column '{request.timeColumn}' does not exist.")
    if target_column not in df.columns and request.aggregation.method != "count":
        raise AppError(f"Target column '{target_column}' does not exist.")

    original_count = len(df)
    method = request.aggregation.method if request.dataMode == "raw" or request.aggregation.enabled else request.duplicateTimeStrategy
    cleaned = clean_source_data(
        df,
        request.timeColumn,
        target_column,
        count_mode=method == "count",
        missing_strategy=request.missingValueStrategy,
        trim_strings=request.trimStrings,
    )
    working = cleaned.frame
    if working.empty:
        if cleaned.invalid_time_count == original_count:
            raise AppError("No parseable time values were found in the selected time column.")
        raise AppError("No valid target values remain after data cleaning.")

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

    valid_count = len(working)
    if valid_count < 2:
        raise AppError("Fewer than two valid time series points remain after parsing.")

    working["_bucket_time"] = _normalize_time(working["_parsed_time"], frequency)
    duplicate_time_count = int(working.duplicated("_bucket_time").sum())

    if request.dataMode == "raw" or request.aggregation.enabled:
        grouped = working.groupby("_bucket_time")["_target_value"].agg(method).reset_index()
    else:
        grouped = working.groupby("_bucket_time", sort=True)["_target_value"].agg(request.duplicateTimeStrategy).reset_index()
    grouped.columns = ["time", "value"]
    grouped = grouped.sort_values("time")

    grouped, missing_time_count, filled_gap_count = _fill_missing(
        grouped,
        frequency,
        request.missingValueStrategy,
        request.fillMissingTimeSteps,
    )

    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce")
    grouped = grouped.dropna(subset=["value"])
    grouped, outlier_count, outlier_adjusted_count = detect_and_handle_outliers(
        grouped,
        request.outlierStrategy,
        request.outlierIqrMultiplier,
    )

    if len(grouped) < 3:
        raise AppError("Fewer than three valid time series points remain after aggregation.")

    warnings = list(frequency_warnings)
    if len(grouped) < 30:
        warnings.append("Valid time points are fewer than 30; forecast comparison may be unstable.")
    if duplicate_time_count and request.dataMode == "aggregated":
        warnings.append(
            f"Duplicate timestamps were found and resolved with '{request.duplicateTimeStrategy}'."
        )
    if missing_time_count:
        action = f"handled with '{request.missingValueStrategy}'" if request.fillMissingTimeSteps else "detected but not inserted"
        warnings.append(f"{missing_time_count} missing time steps were {action} for the regular {frequency} series.")
    if outlier_count:
        warnings.append(
            f"Detected {outlier_count} IQR outliers"
            + (f"; adjusted {outlier_adjusted_count} by clipping." if outlier_adjusted_count else "; values were not changed.")
        )

    points = [
        TimeSeriesPoint(time=row.time.to_pydatetime() if hasattr(row.time, "to_pydatetime") else row.time, value=float(row.value))
        for row in grouped.itertuples(index=False)
    ]
    diagnostics = Diagnostics(
        originalRowCount=original_count,
        validRowCount=len(points),
        droppedRowCount=cleaned.dropped_source_row_count,
        duplicateTimeCount=duplicate_time_count,
        missingTimeCount=missing_time_count,
        invalidTimeCount=cleaned.invalid_time_count,
        inputMissingTargetCount=cleaned.input_missing_target_count,
        invalidTargetCount=cleaned.invalid_target_count,
        filledValueCount=cleaned.filled_target_count + filled_gap_count,
        outlierCount=outlier_count,
        outlierAdjustedCount=outlier_adjusted_count,
        cleaningActions=cleaned.actions,
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
        "cleaning": {
            "missingValueStrategy": request.missingValueStrategy,
            "fillMissingTimeSteps": request.fillMissingTimeSteps,
            "duplicateTimeStrategy": request.duplicateTimeStrategy,
            "outlierStrategy": request.outlierStrategy,
            "outlierIqrMultiplier": request.outlierIqrMultiplier,
            "trimStrings": request.trimStrings,
        },
        "history": [HistoryPoint(time=point.time.isoformat(), value=point.value).model_dump() for point in points],
    }
    return BuildResult(
        series=TimeSeriesData(targetColumn=target_column, frequency=frequency, points=points, diagnostics=diagnostics),
        data_profile=data_profile,
    )
