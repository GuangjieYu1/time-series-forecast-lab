from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.time_parser import parse_datetime_value


@dataclass
class SourceCleaningResult:
    frame: pd.DataFrame
    invalid_time_count: int
    input_missing_target_count: int
    invalid_target_count: int
    filled_target_count: int
    dropped_source_row_count: int
    actions: list[str]


def _blank_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.isna() | text.eq("")


def clean_source_data(
    df: pd.DataFrame,
    time_column: str,
    target_column: str,
    count_mode: bool,
    missing_strategy: str,
    trim_strings: bool,
) -> SourceCleaningResult:
    working = df.copy()
    actions: list[str] = []

    if trim_strings:
        for column in {time_column, target_column}:
            if column in working.columns and (
                pd.api.types.is_object_dtype(working[column]) or pd.api.types.is_string_dtype(working[column])
            ):
                working[column] = working[column].astype("string").str.strip()
        actions.append("已清理所选字段首尾空白。")

    parsed_times = [parse_datetime_value(value) for value in working[time_column].tolist()]
    valid_time_mask = pd.Series(
        [item.ok and item.value is not None for item in parsed_times],
        index=working.index,
        dtype=bool,
    )
    invalid_time_count = int((~valid_time_mask).sum())
    working = working.loc[valid_time_mask].copy()
    working["_parsed_time"] = [item.value for item in parsed_times if item.ok and item.value is not None]

    input_missing_target_count = 0
    invalid_target_count = 0
    filled_target_count = 0
    if count_mode:
        working["_target_value"] = 1.0
    else:
        source = working[target_column]
        missing_mask = _blank_mask(source)
        input_missing_target_count = int(missing_mask.sum())
        normalized = source
        if pd.api.types.is_object_dtype(source) or pd.api.types.is_string_dtype(source):
            normalized = source.astype("string").str.replace(",", "", regex=False).str.strip()
        numeric = pd.to_numeric(normalized, errors="coerce").replace([np.inf, -np.inf], np.nan)
        invalid_target_count = int((numeric.isna() & ~missing_mask).sum())
        working["_target_value"] = numeric
        working = working.sort_values("_parsed_time", kind="stable")

        missing_before = int(working["_target_value"].isna().sum())
        if missing_strategy == "zero":
            working["_target_value"] = working["_target_value"].fillna(0.0)
        elif missing_strategy == "ffill":
            working["_target_value"] = working["_target_value"].ffill().bfill()
        elif missing_strategy == "interpolate":
            working["_target_value"] = working["_target_value"].interpolate(
                method="linear",
                limit_direction="both",
            )
        else:
            working = working.dropna(subset=["_target_value"])
        missing_after = int(working["_target_value"].isna().sum())
        filled_target_count = max(0, missing_before - missing_after) if missing_strategy != "drop" else 0
        working = working.dropna(subset=["_target_value"])

    dropped_source_row_count = len(df) - len(working)
    if invalid_time_count:
        actions.append(f"已移除 {invalid_time_count} 行无法解析的时间。")
    if input_missing_target_count or invalid_target_count:
        if missing_strategy == "drop":
            actions.append("已移除目标值缺失或无法转换为数值的行。")
        else:
            actions.append(f"已使用 {missing_strategy} 处理缺失或无效目标值。")

    return SourceCleaningResult(
        frame=working,
        invalid_time_count=invalid_time_count,
        input_missing_target_count=input_missing_target_count,
        invalid_target_count=invalid_target_count,
        filled_target_count=filled_target_count,
        dropped_source_row_count=dropped_source_row_count,
        actions=actions,
    )


def detect_and_handle_outliers(
    series_df: pd.DataFrame,
    strategy: str,
    iqr_multiplier: float,
) -> tuple[pd.DataFrame, int, int]:
    if len(series_df) < 4:
        return series_df, 0, 0
    values = series_df["value"].astype(float)
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1
    if not np.isfinite(iqr) or iqr <= 0:
        return series_df, 0, 0
    lower = q1 - iqr_multiplier * iqr
    upper = q3 + iqr_multiplier * iqr
    mask = (values < lower) | (values > upper)
    outlier_count = int(mask.sum())
    adjusted_count = 0
    if strategy == "clip_iqr" and outlier_count:
        series_df = series_df.copy()
        series_df["value"] = values.clip(lower=lower, upper=upper)
        adjusted_count = outlier_count
    return series_df, outlier_count, adjusted_count
