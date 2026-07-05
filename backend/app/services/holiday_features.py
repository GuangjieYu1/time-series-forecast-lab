from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import AppError
from app.schemas import HolidayConfig, RuntimeFeatureVisualizationMarker


HOLIDAY_FEATURE_NAMES = [
    "holiday_is_period",
    "holiday_count",
    "holiday_days_since_previous",
    "holiday_days_to_next",
    "holiday_is_window",
]

COUNTRY_NAMES_ZH = {
    "CN": "中国", "US": "美国", "GB": "英国", "JP": "日本", "KR": "韩国",
    "DE": "德国", "FR": "法国", "SG": "新加坡", "AU": "澳大利亚", "CA": "加拿大",
}


@dataclass
class HolidayFeatureResult:
    matrix: np.ndarray
    names: list[str]
    markers: list[RuntimeFeatureVisualizationMarker]


def _library():
    try:
        import holidays
    except Exception as exc:
        raise AppError("节假日日历依赖未安装，请安装 holidays>=0.95。", code="HOLIDAY_LIBRARY_UNAVAILABLE") from exc
    return holidays


def holiday_calendar_catalog() -> dict[str, Any]:
    holidays = _library()
    supported = holidays.list_supported_countries()
    countries = []
    for code, subdivisions in sorted(supported.items()):
        if len(code) != 2:
            continue
        countries.append({
            "code": code,
            "name": COUNTRY_NAMES_ZH.get(code, code),
            "subdivisions": list(subdivisions or []),
        })
    return {"defaultCountryCode": "CN", "countries": countries}


def _period_end(value: datetime, frequency: str) -> datetime:
    stamp = pd.Timestamp(value)
    if frequency == "H":
        return (stamp + pd.Timedelta(hours=1)).to_pydatetime()
    if frequency == "D":
        return (stamp + pd.Timedelta(days=1)).to_pydatetime()
    if frequency == "W":
        return (stamp + pd.Timedelta(days=7)).to_pydatetime()
    if frequency == "M":
        return (stamp + pd.offsets.MonthBegin(1)).to_pydatetime()
    if frequency == "Q":
        return (stamp + pd.offsets.QuarterBegin(startingMonth=1)).to_pydatetime()
    if frequency == "Y":
        return (stamp + pd.offsets.YearBegin(1)).to_pydatetime()
    return (stamp + pd.Timedelta(days=1)).to_pydatetime()


def build_holiday_features(times: list[datetime], frequency: str, config: HolidayConfig) -> HolidayFeatureResult:
    if not times or not config.enabled:
        return HolidayFeatureResult(np.empty((len(times), 0)), [], [])
    holidays = _library()
    years = range(min(value.year for value in times) - 1, max(value.year for value in times) + 2)
    try:
        calendar = holidays.country_holidays(
            config.countryCode.upper(),
            subdiv=config.subdivision or None,
            years=years,
            observed=config.observed,
        )
    except Exception as exc:
        raise AppError(
            f"无法加载国家/地区节假日日历：{config.countryCode}。",
            code="INVALID_HOLIDAY_CALENDAR",
            details={"countryCode": config.countryCode, "subdivision": config.subdivision},
        ) from exc

    holiday_dates = sorted(calendar.keys())
    rows: list[list[float]] = []
    for value in times:
        start = value.date()
        end = _period_end(value, frequency).date()
        in_period = [item for item in holiday_dates if start <= item < end]
        previous = max((item for item in holiday_dates if item <= start), default=None)
        following = min((item for item in holiday_dates if item >= start), default=None)
        since_previous = (start - previous).days if previous else 366
        to_next = (following - start).days if following else 366
        nearest = min(since_previous, to_next)
        rows.append([
            1.0 if in_period else 0.0,
            float(len(in_period)),
            float(since_previous),
            float(to_next),
            1.0 if nearest <= config.windowDays else 0.0,
        ])

    range_start = min(times).date()
    range_end = _period_end(max(times), frequency).date()
    markers = [
        RuntimeFeatureVisualizationMarker(time=item.isoformat(), label=str(calendar[item]), kind="holiday")
        for item in holiday_dates
        if range_start <= item < range_end
    ]
    return HolidayFeatureResult(np.asarray(rows, dtype=float), list(HOLIDAY_FEATURE_NAMES), markers)


def holiday_row(value: datetime, frequency: str, config: HolidayConfig) -> dict[str, float]:
    result = build_holiday_features([value], frequency, config)
    if not result.names:
        return {}
    return {name: float(result.matrix[0, index]) for index, name in enumerate(result.names)}