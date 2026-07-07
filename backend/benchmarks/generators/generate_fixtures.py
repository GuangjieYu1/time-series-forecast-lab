from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from app.core.constants import DEFAULT_RANDOM_SEED


def _write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _hourly_rows(count: int) -> list[list[object]]:
    rng = random.Random(DEFAULT_RANDOM_SEED)
    base = datetime(2024, 1, 1, 0, 0, 0)
    rows: list[list[object]] = []
    for index in range(count):
        moment = base + timedelta(hours=index)
        seasonal = 18 * ((index % 24) / 24)
        trend = index * 0.02
        noise = rng.uniform(-1.5, 1.5)
        rows.append([moment.isoformat(sep=" "), round(100 + seasonal + trend + noise, 4)])
    return rows


def _feature_lift_rows(noise: bool = False, leakage: bool = False) -> list[list[object]]:
    rng = random.Random(DEFAULT_RANDOM_SEED + (2 if noise else 1))
    base = datetime(2024, 1, 1)
    rows: list[list[object]] = []
    for index in range(120):
        moment = base + timedelta(days=index)
        promo = 1 if index in {15, 16, 17, 42, 43, 70, 71, 72, 101, 102, 103} else 0
        holiday = 1 if moment.weekday() >= 5 else 0
        noise_value = rng.uniform(-2.0, 2.0)
        covariate = rng.randint(0, 1) if noise else promo
        value = 100 + index * 0.08 + 38 * promo + 8 * holiday + noise_value
        future_truth = value + 3 if leakage else rng.uniform(0, 1)
        rows.append([moment.strftime("%Y-%m-%d"), round(value, 4), covariate, holiday, round(future_truth, 4)])
    return rows


def ensure_benchmark_fixtures(backend_root: Path | None = None) -> Path:
    root = backend_root or Path(__file__).resolve().parents[2]
    fixture_root = root / "benchmarks" / "fixtures"

    clean_rows = [[f"2024-01-{day:02d}", 100 + day * 2] for day in range(1, 91)]
    _write_csv(fixture_root / "clean" / "daily_clean.csv", ["date", "value"], clean_rows)

    dirty_rows = clean_rows[:20] + [["2024-01-05", 125], ["2024/01/21", ""], ["not-a-date", 132], ["2024-02-03", 9999], ["2024-02-04", 130]] + clean_rows[20:75]
    _write_csv(fixture_root / "dirty" / "daily_dirty.csv", ["date", "value"], dirty_rows)

    edge_rows = [[f"2024-03-{day:02d}", 10 + day] for day in range(1, 13)]
    _write_csv(fixture_root / "edge" / "daily_edge_short.csv", ["date", "value"], edge_rows)

    raw_rows = [
        ["CZ002", "2024-01-01", "CAN", 20, 1],
        ["CZ001", "2024-01-01", "CAN", 10, 1],
        ["CZ003", "2024-01-02", "SZX", "", 0],
        ["CZ004", "2024-01-02", "SZX", 12, 0],
        ["CZ005", "2024-01-03", "PVG", 30, 1],
        ["CZ006", "2024-01-04", "PVG", 7, 0],
        ["CZ007", "2024-01-04", "PVG", 11, 0],
        ["CZ008", "2024-01-05", "CAN", 20, 1],
        ["CZ009", "2024-01-06", "CAN", 13, 1],
        ["CZ010", "2024-01-06", "CAN", 15, 1],
    ]
    _write_csv(fixture_root / "aggregation" / "raw_detail.csv", ["flight_no", "flight_date", "airport", "passenger_count", "promo"], raw_rows)
    _write_csv(fixture_root / "feature_lift" / "positive_covariate.csv", ["date", "value", "promo", "weekend", "future_truth"], _feature_lift_rows(noise=False, leakage=True))
    _write_csv(fixture_root / "feature_lift" / "noise_covariate.csv", ["date", "value", "promo", "weekend", "future_truth"], _feature_lift_rows(noise=True, leakage=True))

    large_path = fixture_root / "large" / "large_hourly.csv"
    if not large_path.exists():
        _write_csv(large_path, ["date", "value"], _hourly_rows(120000))

    return fixture_root


def main() -> None:
    ensure_benchmark_fixtures()


if __name__ == "__main__":
    main()
