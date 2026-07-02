from __future__ import annotations

from app.schemas import Diagnostics
from app.services.data_health import build_data_health_report


def test_clean_series_scores_high():
    report = build_data_health_report(
        Diagnostics(
            originalRowCount=120,
            validRowCount=120,
            droppedRowCount=0,
            duplicateTimeCount=0,
            missingTimeCount=0,
            invalidTimeCount=0,
            inputMissingTargetCount=0,
            invalidTargetCount=0,
            filledValueCount=0,
            outlierCount=0,
            outlierAdjustedCount=0,
            cleaningActions=[],
            timeStart="2026-01-01T00:00:00",
            timeEnd="2026-04-30T00:00:00",
            warnings=[],
        ),
        detected_frequency="D",
        horizon=14,
        test_size=14,
    )

    assert report is not None
    assert report.score >= 90
    assert report.level == "excellent"
    assert report.diagnostics.timeContinuous is True
    assert report.diagnostics.trainSizeSufficient is True


def test_short_dirty_series_produces_warnings_and_suggestions():
    report = build_data_health_report(
        Diagnostics(
            originalRowCount=28,
            validRowCount=22,
            droppedRowCount=6,
            duplicateTimeCount=2,
            missingTimeCount=3,
            invalidTimeCount=1,
            inputMissingTargetCount=2,
            invalidTargetCount=1,
            filledValueCount=0,
            outlierCount=2,
            outlierAdjustedCount=0,
            cleaningActions=["drop invalid rows"],
            timeStart="2026-01-01T00:00:00",
            timeEnd="2026-01-24T00:00:00",
            warnings=["Valid time points are fewer than 30; forecast comparison may be unstable."],
        ),
        detected_frequency="D",
        horizon=7,
        test_size=7,
    )

    assert report is not None
    assert report.score < 75
    assert report.level in {"fair", "poor"}
    assert any("非法时间值" in warning for warning in report.warnings)
    assert any("目标列缺失" in warning for warning in report.warnings)
    assert any("IQR clipping" in suggestion for suggestion in report.suggestions)
    assert report.diagnostics.timeContinuous is False
    assert report.diagnostics.trainSizeSufficient is False
