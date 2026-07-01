from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

from app.schemas import ParsedDateTime


DATETIME_FORMATS = [
    ("%Y-%m-%d %H:%M:%S", "datetime_dash"),
    ("%Y/%m/%d %H:%M:%S", "datetime_slash"),
    ("%Y-%m-%dT%H:%M:%S", "datetime_iso"),
    ("%Y-%m-%d", "date_dash"),
    ("%Y/%m/%d", "date_slash"),
    ("%Y.%m.%d", "date_dot"),
    ("%Y%m%d", "yyyyMMdd"),
    ("%Y-%m", "year_month_dash"),
    ("%Y/%m", "year_month_slash"),
    ("%Y", "year_only"),
]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and value.strip() == ""


def _parse_numeric_text(value: str) -> int | float | None:
    text = value.strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _parse_yyyymmdd(value: int | str) -> ParsedDateTime | None:
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        try:
            parsed = datetime.strptime(text, "%Y%m%d")
            if 1900 <= parsed.year <= 2100:
                return ParsedDateTime(ok=True, value=parsed, source_format="yyyyMMdd")
        except ValueError:
            return None
    return None


def _parse_excel_serial(value: int | float) -> ParsedDateTime | None:
    if not (1 <= float(value) <= 80000):
        return None
    base = datetime(1899, 12, 30)
    parsed = base + timedelta(days=float(value))
    if parsed.year < 1900 or parsed.year > 2200:
        return None
    return ParsedDateTime(ok=True, value=parsed, source_format="excel_serial_date")


def _parse_unix_timestamp(value: int | float) -> ParsedDateTime | None:
    numeric = float(value)
    try:
        if 1_000_000_000_000 <= numeric <= 4_102_444_800_000:
            return ParsedDateTime(
                ok=True,
                value=datetime.fromtimestamp(numeric / 1000, tz=timezone.utc).replace(tzinfo=None),
                source_format="unix_timestamp_milliseconds",
            )
        if 1_000_000_000 <= numeric <= 4_102_444_800:
            return ParsedDateTime(
                ok=True,
                value=datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None),
                source_format="unix_timestamp_seconds",
            )
    except (OverflowError, ValueError, OSError):
        return None
    return None


def parse_datetime_value(value: Any) -> ParsedDateTime:
    if _is_missing(value):
        return ParsedDateTime(ok=False, value=None, source_format=None, warning="empty value")

    if isinstance(value, datetime):
        return ParsedDateTime(ok=True, value=value.replace(tzinfo=None), source_format="python_datetime")

    if isinstance(value, date):
        return ParsedDateTime(ok=True, value=datetime(value.year, value.month, value.day), source_format="python_date")

    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        as_int = int(value)
        yyyymmdd = _parse_yyyymmdd(as_int)
        if yyyymmdd:
            return yyyymmdd
        unix = _parse_unix_timestamp(value)
        if unix:
            return unix
        excel = _parse_excel_serial(value)
        if excel:
            return excel

    text = str(value).strip()
    if not text:
        return ParsedDateTime(ok=False, value=None, source_format=None, warning="empty value")

    if re.fullmatch(r"\d{4}", text):
        try:
            return ParsedDateTime(ok=True, value=datetime.strptime(text, "%Y"), source_format="year_only")
        except ValueError:
            pass

    # Chinese date formats are represented with escapes to keep this source ASCII.
    chinese_date = re.fullmatch(r"(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5", text)
    if chinese_date:
        try:
            return ParsedDateTime(
                ok=True,
                value=datetime(int(chinese_date.group(1)), int(chinese_date.group(2)), int(chinese_date.group(3))),
                source_format="date_chinese",
            )
        except ValueError as exc:
            return ParsedDateTime(ok=False, value=None, source_format="date_chinese", warning=str(exc))

    chinese_month = re.fullmatch(r"(\d{4})\u5e74(\d{1,2})\u6708", text)
    if chinese_month:
        try:
            return ParsedDateTime(
                ok=True,
                value=datetime(int(chinese_month.group(1)), int(chinese_month.group(2)), 1),
                source_format="year_month_chinese",
            )
        except ValueError as exc:
            return ParsedDateTime(ok=False, value=None, source_format="year_month_chinese", warning=str(exc))

    numeric_text = _parse_numeric_text(text)
    if numeric_text is not None:
        yyyymmdd = _parse_yyyymmdd(int(numeric_text)) if float(numeric_text).is_integer() else None
        if yyyymmdd:
            return yyyymmdd
        unix = _parse_unix_timestamp(numeric_text)
        if unix:
            return unix
        excel = _parse_excel_serial(numeric_text)
        if excel:
            return excel

    for fmt, name in DATETIME_FORMATS:
        try:
            return ParsedDateTime(ok=True, value=datetime.strptime(text, fmt), source_format=name)
        except ValueError:
            continue

    try:
        import pandas as pd

        parsed = pd.to_datetime(text, errors="coerce")
        if parsed is not pd.NaT:
            return ParsedDateTime(ok=True, value=parsed.to_pydatetime().replace(tzinfo=None), source_format="pandas_auto")
    except Exception:
        pass

    return ParsedDateTime(ok=False, value=None, source_format=None, warning="unrecognized datetime format")


def detect_frequency(values: list[Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    parsed = [parse_datetime_value(value) for value in values if not _is_missing(value)]
    ok = [item for item in parsed if item.ok and item.value is not None]
    if len(ok) < 2:
        return "D", ["Unable to identify frequency with fewer than two valid timestamps; defaulted to D."]

    formats = {item.source_format for item in ok}
    month_formats = {"year_month_dash", "year_month_slash", "year_month_chinese"}
    if formats and formats.issubset({"year_only"}):
        return "Y", warnings
    if formats and formats.issubset(month_formats):
        return "M", warnings

    unique_dates = sorted({item.value for item in ok if item.value is not None})
    if len(unique_dates) < 2:
        return "D", ["Only one unique timestamp was found; defaulted to D."]

    deltas = [(right - left).total_seconds() for left, right in zip(unique_dates, unique_dates[1:]) if right > left]
    if not deltas:
        return "D", ["Timestamps do not have positive intervals; defaulted to D."]

    step = median(deltas)
    day = 24 * 60 * 60
    hour = 60 * 60

    if step <= 1.5 * hour:
        return "H", warnings
    if 0.75 * day <= step <= 1.5 * day:
        return "D", warnings
    if 5.5 * day <= step <= 8.5 * day:
        return "W", warnings
    if 25 * day <= step <= 35 * day:
        return "M", warnings
    if 80 * day <= step <= 100 * day:
        return "Q", warnings
    if 340 * day <= step <= 390 * day:
        return "Y", warnings

    warnings.append(f"Frequency interval {step} seconds is irregular; defaulted to D.")
    return "D", warnings
