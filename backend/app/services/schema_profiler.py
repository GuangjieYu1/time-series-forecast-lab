from __future__ import annotations

from typing import Any

from app.schemas import ColumnProfile
from app.services.time_parser import parse_datetime_value


TIME_COLUMN_HINTS = ("date", "time", "datetime", "timestamp", "month", "year", "日期", "时间", "年月", "月份", "年度")


def _is_null(value: Any) -> bool:
    return value is None or value == ""


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _has_time_name_hint(column_name: str | None) -> bool:
    normalized = (column_name or "").strip().lower()
    return any(hint in normalized for hint in TIME_COLUMN_HINTS)


def _looks_like_unambiguous_numeric_datetime(value: Any) -> bool:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit() and len(text) == 8:
        year = int(text[:4])
        return 1900 <= year <= 2200 and parse_datetime_value(value).ok
    return False


def infer_column_type(values: list[Any], column_name: str | None = None) -> str:
    non_null = [value for value in values if not _is_null(value)]
    if not non_null:
        return "empty"

    number_hits = 0
    bool_hits = 0
    for value in non_null:
        if isinstance(value, bool) or str(value).strip().lower() in {"true", "false", "yes", "no"}:
            bool_hits += 1
        try:
            float(value)
            number_hits += 1
        except (TypeError, ValueError):
            pass

    if bool_hits == len(non_null):
        return "boolean"
    if number_hits == len(non_null):
        unambiguous_time_hits = sum(_looks_like_unambiguous_numeric_datetime(value) for value in non_null)
        if unambiguous_time_hits >= max(2, int(len(non_null) * 0.7)):
            return "datetime"
        if _has_time_name_hint(column_name):
            datetime_hits = sum(1 for value in non_null if parse_datetime_value(value).ok)
            if datetime_hits >= max(2, int(len(non_null) * 0.7)):
                return "datetime"
        return "number"

    datetime_hits = sum(1 for value in non_null if parse_datetime_value(value).ok)
    if datetime_hits >= max(2, int(len(non_null) * 0.7)):
        return "datetime"
    return "string"


def profile_columns(rows: list[dict[str, Any]], column_names: list[str]) -> list[ColumnProfile]:
    profiles: list[ColumnProfile] = []
    for column in column_names:
        values = [row.get(column) for row in rows]
        non_null = [value for value in values if not _is_null(value)]
        samples: list[Any] = []
        for value in non_null:
            normalized = _json_value(value)
            if normalized not in samples:
                samples.append(normalized)
            if len(samples) == 5:
                break
        profiles.append(
            ColumnProfile(
                name=column,
                inferredType=infer_column_type(values, column),
                sampleValues=samples,
                nonNullCountInPreview=len(non_null),
                nullCountInPreview=len(values) - len(non_null),
            )
        )
    return profiles
