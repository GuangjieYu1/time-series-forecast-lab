from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.errors import AppError
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


def _fill_numeric(series: pd.Series, strategy: str, *, time_index: pd.Series | None = None, limit: int | None = None) -> pd.Series:
    if strategy == "zero":
        return series.fillna(0.0)
    if strategy == "ffill":
        return series.ffill().bfill()
    if strategy == "bfill":
        return series.bfill().ffill()
    if strategy == "median":
        median = series.median()
        return series.fillna(float(median) if pd.notna(median) else 0.0)
    if strategy == "interpolate":
        return series.interpolate(method="linear", limit=limit, limit_direction="both")
    if strategy == "time" and time_index is not None:
        indexed = pd.Series(series.to_numpy(), index=pd.to_datetime(time_index), dtype=float)
        return pd.Series(
            indexed.interpolate(method="time", limit=limit, limit_direction="both").to_numpy(),
            index=series.index,
            dtype=float,
        )
    return series


def clean_source_data(
    df: pd.DataFrame,
    time_column: str,
    target_column: str,
    count_mode: bool,
    missing_strategy: str,
    trim_strings: bool,
    *,
    invalid_time_strategy: str = "drop",
    normalize_thousands_separators: bool = True,
    sort_by_time: bool = True,
    interpolation_limit: int | None = None,
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
    if invalid_time_count and invalid_time_strategy == "error":
        raise AppError(
            f"时间列中有 {invalid_time_count} 个无法解析的值，请修正后重试或改为删除无效时间。",
            code="INVALID_TIME_VALUES",
            details={"invalidTimeCount": invalid_time_count},
        )
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
            normalized = source.astype("string").str.strip()
            if normalize_thousands_separators:
                normalized = normalized.str.replace(",", "", regex=False)
        numeric = pd.to_numeric(normalized, errors="coerce").replace([np.inf, -np.inf], np.nan)
        invalid_target_count = int((numeric.isna() & ~missing_mask).sum())
        working["_target_value"] = numeric
        if sort_by_time:
            working = working.sort_values("_parsed_time", kind="stable")
            actions.append("已按时间升序排列数据。")

        missing_before = int(working["_target_value"].isna().sum())
        if missing_strategy == "drop":
            working = working.dropna(subset=["_target_value"])
        else:
            working["_target_value"] = _fill_numeric(
                working["_target_value"],
                missing_strategy,
                time_index=working["_parsed_time"],
                limit=interpolation_limit,
            )
        missing_after = int(working["_target_value"].isna().sum())
        filled_target_count = max(0, missing_before - missing_after)
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
    hampel_window: int = 7,
    hampel_sigma: float = 3.0,
) -> tuple[pd.DataFrame, int, int]:
    if len(series_df) < 4:
        return series_df, 0, 0
    values = series_df["value"].astype(float)

    if strategy == "hampel":
        window = max(3, int(hampel_window))
        if window % 2 == 0:
            window += 1
        rolling_median = values.rolling(window, center=True, min_periods=max(3, window // 2)).median()
        deviation = (values - rolling_median).abs()
        rolling_mad = deviation.rolling(window, center=True, min_periods=max(3, window // 2)).median()
        threshold = 1.4826 * float(hampel_sigma) * rolling_mad
        mask = threshold.gt(0) & deviation.gt(threshold)
        outlier_count = int(mask.sum())
        if not outlier_count:
            return series_df, 0, 0
        result = series_df.copy()
        result.loc[mask, "value"] = rolling_median.loc[mask]
        return result, outlier_count, outlier_count

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