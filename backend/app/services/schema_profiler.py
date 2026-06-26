from __future__ import annotations

from typing import Any

from app.schemas import ColumnProfile
from app.services.time_parser import parse_datetime_value


def _is_null(value: Any) -> bool:
    return value is None or value == ""


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def infer_column_type(values: list[Any]) -> str:
    non_null = [value for value in values if not _is_null(value)]
    if not non_null:
        return "empty"

    datetime_hits = sum(1 for value in non_null if parse_datetime_value(value).ok)
    if datetime_hits >= max(2, int(len(non_null) * 0.7)):
        return "datetime"

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

    if number_hits == len(non_null):
        return "number"
    if bool_hits == len(non_null):
        return "boolean"
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
                inferredType=infer_column_type(values),
                sampleValues=samples,
                nonNullCountInPreview=len(non_null),
                nullCountInPreview=len(values) - len(non_null),
            )
        )
    return profiles
