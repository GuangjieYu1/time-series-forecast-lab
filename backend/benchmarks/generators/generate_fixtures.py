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


def ensure_benchmark_fixtures(backend_root: Path | None = None) -> Path:
    root = backend_root or Path(__file__).resolve().parents[2]
    fixture_root = root / "benchmarks" / "fixtures"

    clean_rows = [[f"2024-01-{day:02d}", 100 + day * 2] for day in range(1, 91)]
    _write_csv(fixture_root / "clean" / "daily_clean.csv", ["date", "value"], clean_rows)

    dirty_rows = clean_rows[:20] + [
        ["2024-01-05", 125],
        ["2024/01/21", ""],
        ["not-a-date", 132],
        ["2024-02-03", 9999],
        ["2024-02-04", 130],
    ] + clean_rows[20:75]
    _write_csv(fixture_root / "dirty" / "daily_dirty.csv", ["date", "value"], dirty_rows)

    edge_rows = [[f"2024-03-{day:02d}", 10 + day] for day in range(1, 13)]
    _write_csv(fixture_root / "edge" / "daily_edge_short.csv", ["date", "value"], edge_rows)

    large_path = fixture_root / "large" / "large_hourly.csv"
    if not large_path.exists():
        _write_csv(large_path, ["date", "value"], _hourly_rows(120000))

    return fixture_root


def main() -> None:
    ensure_benchmark_fixtures()


if __name__ == "__main__":
    main()
