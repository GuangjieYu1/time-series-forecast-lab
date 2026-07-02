from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

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
    covariateColumns: list[str] = Field(default_factory=list)
    covariateRows: list[dict[str, float]] = Field(default_factory=list)


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
    fill_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, int, int]:
    if series_df.empty or frequency not in PANDAS_FREQ:
        return series_df, 0, 0
    full_index = pd.date_range(series_df["time"].min(), series_df["time"].max(), freq=PANDAS_FREQ[frequency])
    indexed = series_df.set_index("time").reindex(full_index)
    missing_count = int(indexed["value"].isna().sum())
    feature_columns = [column for column in (fill_columns or indexed.columns.tolist()) if column in indexed.columns]
    if not fill_missing_steps:
        return series_df, missing_count, 0
    if strategy == "zero":
        indexed[feature_columns] = indexed[feature_columns].fillna(0)
    elif strategy == "ffill":
        indexed[feature_columns] = indexed[feature_columns].ffill().bfill()
    elif strategy == "interpolate":
        indexed[feature_columns] = indexed[feature_columns].interpolate(method="linear", limit_direction="both")
        indexed[feature_columns] = indexed[feature_columns].ffill().bfill()
    else:
        indexed = indexed.dropna(subset=["value"])
    filled_count = missing_count if strategy != "drop" else 0
    return indexed.reset_index(names="time"), missing_count, filled_count


def _coerce_covariate_series(series: pd.Series) -> pd.Series:
    values: list[float] = []
    truthy = {"true", "yes", "y", "1", "on"}
    falsy = {"false", "no", "n", "0", "off"}
    for value in series.tolist():
        if pd.isna(value):
            values.append(float("nan"))
            continue
        if isinstance(value, bool):
            values.append(1.0 if value else 0.0)
            continue
        text = str(value).strip().replace(",", "")
        lowered = text.lower()
        if lowered in truthy:
            values.append(1.0)
            continue
        if lowered in falsy:
            values.append(0.0)
            continue
        try:
            values.append(float(text))
        except (TypeError, ValueError):
            values.append(float("nan"))
    return pd.Series(values, index=series.index, dtype=float)


def _resolve_covariate_columns(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for column in request.covariateColumns:
        if column in seen or column in {request.timeColumn, target_column}:
            continue
        if column not in df.columns:
            raise AppError(f"Covariate column '{column}' does not exist.")
        resolved.append(column)
        seen.add(column)
    return resolved


def build_time_series(df: pd.DataFrame, request: ForecastRunRequest, target_column: str) -> BuildResult:
    if request.timeColumn not in df.columns:
        raise AppError(f"Time column '{request.timeColumn}' does not exist.")
    if target_column not in df.columns and request.aggregation.method != "count":
        raise AppError(f"Target column '{target_column}' does not exist.")
    covariate_columns = _resolve_covariate_columns(df, request, target_column)

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
    for column in covariate_columns:
        working[f"_covariate_{column}"] = _coerce_covariate_series(working[column])

    if request.dataMode == "raw" or request.aggregation.enabled:
        grouped = working.groupby("_bucket_time")["_target_value"].agg(method).reset_index()
    else:
        grouped = working.groupby("_bucket_time", sort=True)["_target_value"].agg(request.duplicateTimeStrategy).reset_index()
    grouped.columns = ["time", "value"]
    if covariate_columns:
        covariate_source_columns = [f"_covariate_{column}" for column in covariate_columns]
        covariate_frame = (
            working.groupby("_bucket_time", sort=True)[covariate_source_columns]
            .mean()
            .reset_index()
            .rename(columns={"_bucket_time": "time", **{f"_covariate_{column}": column for column in covariate_columns}})
        )
        grouped = grouped.merge(covariate_frame, on="time", how="left")
    grouped = grouped.sort_values("time")

    grouped, missing_time_count, filled_gap_count = _fill_missing(
        grouped,
        frequency,
        request.missingValueStrategy,
        request.fillMissingTimeSteps,
        fill_columns=["value", *covariate_columns],
    )
    covariate_missing_count = 0
    if covariate_columns:
        covariate_missing_count = int(grouped[covariate_columns].isna().sum().sum())
        if covariate_missing_count:
            grouped[covariate_columns] = grouped[covariate_columns].ffill().bfill().fillna(0.0)

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
    if covariate_missing_count:
        warnings.append(f"{covariate_missing_count} missing covariate values were aligned by forward/backward fill, then defaulted to 0 when needed.")
    if outlier_count:
        warnings.append(
            f"Detected {outlier_count} IQR outliers"
            + (f"; adjusted {outlier_adjusted_count} by clipping." if outlier_adjusted_count else "; values were not changed.")
        )

    points = [
        TimeSeriesPoint(time=row.time.to_pydatetime() if hasattr(row.time, "to_pydatetime") else row.time, value=float(row.value))
        for row in grouped.itertuples(index=False)
    ]
    covariate_rows = [
        {column: float(value) for column, value in row.items()}
        for row in grouped[covariate_columns].to_dict(orient="records")
    ] if covariate_columns else []
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
        "covariateColumns": covariate_columns,
        "featureConfig": request.featureConfig.model_dump(),
        "aggregation": method,
        "detectedFrequency": frequency,
        "sourceFrequency": detected_frequency,
        "covariateAggregation": "mean" if covariate_columns else None,
        "cleaning": {
            "missingValueStrategy": request.missingValueStrategy,
            "fillMissingTimeSteps": request.fillMissingTimeSteps,
            "duplicateTimeStrategy": request.duplicateTimeStrategy,
            "outlierStrategy": request.outlierStrategy,
            "outlierIqrMultiplier": request.outlierIqrMultiplier,
            "trimStrings": request.trimStrings,
        },
        "history": [HistoryPoint(time=point.time.isoformat(), value=point.value).model_dump() for point in points],
        "covariateHistory": [
            {"time": point.time.isoformat(), **covariate_row}
            for point, covariate_row in zip(points, covariate_rows)
        ],
    }
    return BuildResult(
        series=TimeSeriesData(
            targetColumn=target_column,
            frequency=frequency,
            points=points,
            diagnostics=diagnostics,
            covariateColumns=covariate_columns,
            covariateRows=covariate_rows,
        ),
        data_profile=data_profile,
    )
