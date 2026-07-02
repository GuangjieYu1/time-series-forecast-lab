from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas import DataHealthDiagnostics, DataHealthReport, Diagnostics


def _safe_rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def extract_detected_frequency(*, data_profile: Any = None, manifest: Any = None) -> str | None:
    if isinstance(manifest, dict):
        targets = manifest.get("targets")
        if isinstance(targets, list) and targets and isinstance(targets[0], dict):
            frequency = targets[0].get("detectedFrequency")
            if isinstance(frequency, str) and frequency:
                return frequency
    if isinstance(data_profile, dict):
        targets = data_profile.get("targets")
        if isinstance(targets, list) and targets and isinstance(targets[0], dict):
            frequency = targets[0].get("detectedFrequency")
            if isinstance(frequency, str) and frequency:
                return frequency
    return None


def build_data_health_report(
    diagnostics: Diagnostics | dict[str, Any] | None,
    *,
    detected_frequency: str | None,
    horizon: int | None,
    test_size: int | None,
) -> DataHealthReport | None:
    if diagnostics is None:
        return None
    try:
        parsed = diagnostics if isinstance(diagnostics, Diagnostics) else Diagnostics.model_validate(diagnostics)
    except Exception:
        return None

    valid_points = max(int(parsed.validRowCount), 0)
    original_rows = max(int(parsed.originalRowCount), 0)
    test_points = min(max(int(test_size or 0), 0), valid_points)
    train_points = max(valid_points - test_points, 0)
    denominator = max(original_rows, 1)
    continuity_total = max(valid_points + parsed.missingTimeCount, 1)

    invalid_time_rate = _safe_rate(parsed.invalidTimeCount, denominator)
    target_missing_rate = _safe_rate(parsed.inputMissingTargetCount + parsed.invalidTargetCount, denominator)
    duplicate_time_rate = _safe_rate(parsed.duplicateTimeCount, max(valid_points, 1))
    missing_time_rate = _safe_rate(parsed.missingTimeCount, continuity_total)
    outlier_rate = _safe_rate(parsed.outlierCount, max(valid_points, 1))
    dropped_row_rate = _safe_rate(parsed.droppedRowCount, denominator)
    continuity_coverage = round(valid_points / continuity_total, 4)

    train_size_threshold = max(24, max(int(test_size or 0), 1) * 3)
    train_size_sufficient = train_points >= train_size_threshold
    test_size_reasonable = valid_points == 0 or (3 <= test_points <= max(8, valid_points // 3))

    score = 100
    score -= round(invalid_time_rate * 500)
    score -= round(target_missing_rate * 400)
    score -= round(duplicate_time_rate * 300)
    score -= round(outlier_rate * 200)
    if parsed.missingTimeCount:
        score -= min(15, max(5, round(missing_time_rate * 100)))
    if valid_points < 30:
        score -= 20
    elif not train_size_sufficient:
        score -= 10
    if not test_size_reasonable:
        score -= 8
    score = max(0, min(100, score))

    if score >= 90:
        level = "excellent"
    elif score >= 75:
        level = "good"
    elif score >= 60:
        level = "fair"
    else:
        level = "poor"

    warnings: list[str] = []
    suggestions: list[str] = []
    if parsed.invalidTimeCount:
        warnings.append(f"检测到 {parsed.invalidTimeCount} 个非法时间值（{_format_percent(invalid_time_rate)}）。")
        suggestions.append("建议统一时间格式后再运行实验。")
    missing_target_count = parsed.inputMissingTargetCount + parsed.invalidTargetCount
    if missing_target_count:
        warnings.append(f"目标列缺失或非法值共 {missing_target_count} 个（{_format_percent(target_missing_rate)}）。")
        suggestions.append("建议优先使用 interpolate 或 ffill 处理目标列缺失。")
    if parsed.duplicateTimeCount:
        warnings.append(f"检测到 {parsed.duplicateTimeCount} 个重复时间点（{_format_percent(duplicate_time_rate)}）。")
        suggestions.append("建议确认重复时间的聚合策略是否符合业务口径。")
    if parsed.missingTimeCount:
        warnings.append(f"规则时间轴上存在 {parsed.missingTimeCount} 个缺口，连续性覆盖率为 {_format_percent(continuity_coverage)}。")
        if parsed.filledValueCount == 0:
            suggestions.append("建议开启缺失时间补点并结合 interpolate/ffill 评估稳定性。")
        else:
            suggestions.append("建议复核补值策略是否会扭曲真实周期或峰值。")
    if parsed.outlierCount:
        warnings.append(f"检测到 {parsed.outlierCount} 个 IQR 异常值（{_format_percent(outlier_rate)}）。")
        if parsed.outlierAdjustedCount == 0:
            suggestions.append("建议启用 IQR clipping，降低异常值对回测指标的扰动。")
        elif parsed.outlierAdjustedCount < parsed.outlierCount:
            suggestions.append("建议检查未被调整的异常值是否需要人工确认。")
    if valid_points < 30:
        warnings.append(f"有效样本仅有 {valid_points} 个，模型比较可能不稳定。")
        suggestions.append("建议增加历史样本，或降低预测粒度后再比较模型。")
    elif not train_size_sufficient:
        warnings.append(f"训练集仅有 {train_points} 个点，低于建议阈值 {train_size_threshold}。")
        suggestions.append("建议扩大训练窗口或适当减小测试集。")
    if not test_size_reasonable:
        warnings.append(f"当前测试集长度为 {test_points}，与总样本 {valid_points} 的比例不够理想。")
        suggestions.append("建议将测试集长度控制在总样本的 10%~30%，并至少保留 3 个点。")

    warnings.extend(parsed.warnings)
    unique_suggestions = list(dict.fromkeys(suggestions))

    start = _parse_iso_datetime(parsed.timeStart)
    end = _parse_iso_datetime(parsed.timeEnd)
    span_days = None
    if start and end:
        span_days = round((end - start).total_seconds() / 86400, 2)

    return DataHealthReport(
        score=score,
        level=level,
        warnings=warnings,
        suggestions=unique_suggestions,
        diagnostics=DataHealthDiagnostics(
            frequency=detected_frequency,
            validPointCount=valid_points,
            trainPointCount=train_points,
            testPointCount=test_points,
            originalRowCount=original_rows,
            droppedRowRate=dropped_row_rate,
            invalidTimeRate=invalid_time_rate,
            targetMissingRate=target_missing_rate,
            duplicateTimeRate=duplicate_time_rate,
            missingTimeRate=missing_time_rate,
            outlierRate=outlier_rate,
            continuityCoverage=continuity_coverage,
            timeContinuous=parsed.missingTimeCount == 0,
            trainSizeSufficient=train_size_sufficient,
            testSizeReasonable=test_size_reasonable,
            timeStart=parsed.timeStart,
            timeEnd=parsed.timeEnd,
            timeSpanDays=span_days,
        ),
    )
