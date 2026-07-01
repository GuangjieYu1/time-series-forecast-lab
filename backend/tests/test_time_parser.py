from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.series_builder import is_frequency_allowed
from app.services.time_parser import detect_frequency, parse_datetime_value


@pytest.mark.parametrize(
    ("value", "source_format", "expected"),
    [
        ("2026-06-01", "date_dash", datetime(2026, 6, 1)),
        ("2026/06/01", "date_slash", datetime(2026, 6, 1)),
        ("2026.06.01", "date_dot", datetime(2026, 6, 1)),
        ("20260601", "yyyyMMdd", datetime(2026, 6, 1)),
        (20230102, "yyyyMMdd", datetime(2023, 1, 2)),
        ("2.0230102E7", "yyyyMMdd", datetime(2023, 1, 2)),
        ("2026-06", "year_month_dash", datetime(2026, 6, 1)),
        ("2026/06", "year_month_slash", datetime(2026, 6, 1)),
        ("2026\u5e746\u67081\u65e5", "date_chinese", datetime(2026, 6, 1)),
        ("2026\u5e746\u6708", "year_month_chinese", datetime(2026, 6, 1)),
        ("2026-06-01 12:00:00", "datetime_dash", datetime(2026, 6, 1, 12, 0, 0)),
    ],
)
def test_parse_datetime_formats(value, source_format, expected):
    parsed = parse_datetime_value(value)
    assert parsed.ok
    assert parsed.source_format == source_format
    assert parsed.value == expected


def test_parse_excel_serial_date():
    serial = (datetime(2026, 6, 1) - datetime(1899, 12, 30)).days
    parsed = parse_datetime_value(serial)
    assert parsed.ok
    assert parsed.source_format == "excel_serial_date"
    assert parsed.value == datetime(2026, 6, 1)


def test_parse_unix_seconds_and_milliseconds():
    timestamp = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    seconds = parse_datetime_value(timestamp)
    milliseconds = parse_datetime_value(timestamp * 1000)
    assert seconds.source_format == "unix_timestamp_seconds"
    assert milliseconds.source_format == "unix_timestamp_milliseconds"
    assert seconds.value == datetime(2026, 6, 1)
    assert milliseconds.value == datetime(2026, 6, 1)


def test_detect_frequency_all_supported_grains():
    assert detect_frequency([f"2026-06-01 {hour:02d}:00:00" for hour in range(5)])[0] == "H"
    assert detect_frequency([f"2026-06-{day:02d}" for day in range(1, 6)])[0] == "D"
    assert detect_frequency(["2026-06-01", "2026-06-08", "2026-06-15"])[0] == "W"
    assert detect_frequency(["2026-01", "2026/02", "2026\u5e743\u6708"])[0] == "M"
    assert detect_frequency(["2026-01-01", "2026-04-01", "2026-07-01"])[0] == "Q"
    assert detect_frequency(["2024", "2025", "2026"])[0] == "Y"


def test_frequency_cannot_be_finer_than_source():
    assert not is_frequency_allowed("D", "H")
    assert not is_frequency_allowed("M", "D")
    assert not is_frequency_allowed("M", "H")
    assert is_frequency_allowed("D", "M")
    assert is_frequency_allowed("M", "M")
