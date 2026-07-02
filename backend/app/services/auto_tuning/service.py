from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from app.models.seasonal_naive import SEASONAL_PERIODS
from app.schemas import MetricValues, ModelTuning, TuningTrial
from app.services.metrics import calculate_metrics
from app.services.model_executor import fit_model_instance, predict_model_instance, run_isolated_fit_predict, should_isolate_model
from app.services.model_registry import create_model, normalize_model_parameters


PROFILE_LIMITS = {"fast": 4, "balanced": 7, "accurate": 10}
PROFILE_BUDGET_SECONDS = {"fast": 3.0, "balanced": 8.0, "accurate": 16.0}
SUPPORTED_AUTO_TUNING_MODELS = {
    "seasonal_naive",
    "moving_average",
    "arima",
    "ets",
    "prophet",
    "timesfm",
    "xgboost",
    "lightgbm",
    "random_forest",
}

TuningProgressCallback = Callable[[int, int, str], None]


def describe_tuning_profile(run_profile: str) -> dict[str, float | int]:
    profile = run_profile if run_profile in PROFILE_LIMITS else "balanced"
    return {
        "candidateLimit": PROFILE_LIMITS[profile],
        "timeBudgetSeconds": PROFILE_BUDGET_SECONDS[profile],
    }


def _candidate_grid(model_id: str, base: dict[str, Any], *, frequency: str, series_length: int) -> list[dict[str, Any]]:
    del series_length
    if model_id == "moving_average":
        return [{"window": value} for value in [3, 5, 7, 14, 21, 28]]
    if model_id == "seasonal_naive":
        default_period = int(base.get("period") or SEASONAL_PERIODS.get(frequency, 1) or 1)
        period_candidates = [
            base.get("period") or 0,
            default_period,
            max(1, default_period // 2),
            max(1, default_period - 1),
            default_period + 1,
            default_period * 2,
            1,
        ]
        period_candidates.extend(
            {
                "H": [12, 24, 48, 168],
                "D": [7, 14, 28],
                "W": [13, 26, 52],
                "M": [3, 6, 12, 24],
                "Q": [2, 4, 8],
                "Y": [1, 2, 3],
            }.get(frequency, [])
        )
        return [{"period": int(value)} for value in period_candidates if int(value) >= 0]
    if model_id == "arima":
        return [
            {"p": p, "d": d, "q": q}
            for p, d, q in [(1, 1, 1), (2, 1, 1), (2, 1, 2), (3, 1, 1), (1, 0, 1), (1, 1, 2)]
        ]
    if model_id == "ets":
        return [{"trend": trend} for trend in ["auto", "add", "none"]]
    if model_id == "prophet":
        return [
            {"seasonalityMode": mode, "changepointPriorScale": cps}
            for mode, cps in [
                ("additive", 0.05),
                ("additive", 0.1),
                ("multiplicative", 0.05),
                ("multiplicative", 0.1),
                ("additive", 0.3),
            ]
        ]
    if model_id == "timesfm":
        base_context = int(base.get("maxContext") or 512)
        base_normalize = bool(base.get("normalizeInputs", True))
        context_candidates: list[int] = []
        for value in [base_context, 32, 64, 128, 256, 512]:
            candidate = max(32, min(int(value), 512))
            if candidate not in context_candidates:
                context_candidates.append(candidate)
        candidates: list[dict[str, Any]] = []
        for normalize_inputs in [base_normalize, not base_normalize]:
            for context in context_candidates:
                candidates.append({"maxContext": context, "normalizeInputs": normalize_inputs})
        return candidates
    if model_id == "xgboost":
        return [
            {"nEstimators": n, "maxDepth": depth, "learningRate": rate}
            for n, depth, rate in [(80, 2, 0.08), (120, 3, 0.05), (200, 4, 0.05), (300, 5, 0.03), (400, 6, 0.03)]
        ]
    if model_id == "lightgbm":
        return [
            {"nEstimators": n, "numLeaves": leaves, "learningRate": rate}
            for n, leaves, rate in [(120, 15, 0.08), (200, 31, 0.05), (300, 63, 0.05), (400, 63, 0.03), (500, 127, 0.03)]
        ]
    if model_id == "random_forest":
        return [
            {"nEstimators": n, "maxDepth": depth, "minSamplesLeaf": leaf}
            for n, depth, leaf in [(80, 8, 1), (120, 12, 2), (160, 18, 2), (220, 24, 2), (260, 32, 1)]
        ]
    return [base]


def _canonicalize_candidate(model_id: str, candidate: dict[str, Any], *, frequency: str, series_length: int) -> dict[str, Any]:
    normalized = normalize_model_parameters(model_id, candidate)
    if model_id == "seasonal_naive":
        period = int(normalized.get("period") or SEASONAL_PERIODS.get(frequency, 1) or 1)
        period = max(1, min(period, 8760))
        if series_length < period:
            period = 1
        return {"period": period}
    if model_id == "timesfm":
        effective_context_limit = max(32, series_length)
        return {
            "maxContext": min(int(normalized["maxContext"]), effective_context_limit),
            "normalizeInputs": bool(normalized["normalizeInputs"]),
        }
    return normalized


def _dedupe_candidates(model_id: str, candidates: list[dict[str, Any]], *, frequency: str, series_length: int) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for candidate in candidates:
        normalized = _canonicalize_candidate(model_id, candidate, frequency=frequency, series_length=series_length)
        key = tuple(sorted(normalized.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _evaluate_candidate(
    model_id: str,
    parameters: dict[str, Any],
    train_times: list[datetime],
    train_values: list[float],
    frequency: str,
    test_size: int,
    train_covariates: list[dict[str, float]] | None = None,
    future_covariates: list[dict[str, float]] | None = None,
    feature_config: dict[str, bool] | None = None,
) -> MetricValues:
    if should_isolate_model(model_id):
        output = run_isolated_fit_predict(
            model_id,
            parameters,
            train_times,
            train_values,
            frequency,
            test_size,
            covariates=train_covariates,
            future_covariates=future_covariates,
            feature_config=feature_config,
        )
    else:
        model = create_model(model_id, parameters)
        fit_model_instance(
            model_id,
            model,
            train_times,
            train_values,
            frequency,
            covariates=train_covariates,
            feature_config=feature_config,
        )
        output = predict_model_instance(model_id, model, test_size, future_covariates=future_covariates)
    metrics, _warnings = calculate_metrics(train_values[-test_size:], output.predictions[:test_size])
    return metrics


def resolve_model_parameters(
    *,
    model_id: str,
    requested_parameters: dict[str, Any] | None,
    parameter_strategy: str,
    run_profile: str,
    random_seed: int,
    train_times: list[datetime],
    train_values: list[float],
    frequency: str,
    test_size: int,
    train_covariates: list[dict[str, float]] | None = None,
    future_covariates: list[dict[str, float]] | None = None,
    feature_config: dict[str, bool] | None = None,
    progress_callback: TuningProgressCallback | None = None,
) -> ModelTuning:
    del random_seed
    base = normalize_model_parameters(model_id, requested_parameters)
    strategy_profile = describe_tuning_profile(run_profile)
    candidate_limit = int(strategy_profile["candidateLimit"])
    budget_seconds = float(strategy_profile["timeBudgetSeconds"])
    if parameter_strategy != "auto":
        return ModelTuning(
            enabled=False,
            profile=run_profile,
            strategy=parameter_strategy,
            selectedParams=base,
            candidateCount=1,
            bestMetric=None,
            tuningSeconds=0.0,
            candidateLimit=1,
            timeBudgetSeconds=0.0,
            validationSize=0,
            stoppedEarly=False,
            trials=[],
            warnings=[],
        )

    if model_id not in SUPPORTED_AUTO_TUNING_MODELS:
        return ModelTuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selectedParams=base,
            candidateCount=1,
            bestMetric=None,
            tuningSeconds=0.0,
            candidateLimit=1,
            timeBudgetSeconds=0.0,
            validationSize=0,
            stoppedEarly=False,
            trials=[],
            warnings=[f"{model_id} 暂不支持自动调参，已回退到当前参数。"],
        )

    if len(train_values) < max(18, test_size * 3):
        return ModelTuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selectedParams=base,
            candidateCount=1,
            bestMetric=None,
            tuningSeconds=0.0,
            candidateLimit=candidate_limit,
            timeBudgetSeconds=budget_seconds,
            validationSize=0,
            stoppedEarly=False,
            trials=[],
            warnings=["训练样本不足，自动调参已跳过并回退到当前参数。"],
        )

    validation_size = min(max(test_size, 4), max(4, len(train_values) // 4))
    tune_train_times = train_times[:-validation_size]
    tune_train_values = train_values[:-validation_size]
    tune_test_values = train_values[-validation_size:]
    tune_train_covariates = train_covariates[:-validation_size] if train_covariates else None
    tune_future_covariates = train_covariates[-validation_size:] if train_covariates else future_covariates

    if len(tune_train_values) < 12:
        return ModelTuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selectedParams=base,
            candidateCount=1,
            bestMetric=None,
            tuningSeconds=0.0,
            candidateLimit=candidate_limit,
            timeBudgetSeconds=budget_seconds,
            validationSize=validation_size,
            stoppedEarly=False,
            trials=[],
            warnings=["调参切分后训练样本不足，已回退到当前参数。"],
        )

    candidates = _dedupe_candidates(
        model_id,
        [base, *_candidate_grid(model_id, base, frequency=frequency, series_length=len(tune_train_values))],
        frequency=frequency,
        series_length=len(tune_train_values),
    )
    candidates = candidates[:candidate_limit]
    if progress_callback:
        progress_callback(0, len(candidates), f"正在自动优化参数，共 {len(candidates)} 组候选。")

    warnings: list[str] = []
    trials: list[TuningTrial] = []
    best_metric: float | None = None
    best_params = base
    start = time.perf_counter()
    tried = 0
    stopped_early = False

    for round_index, candidate in enumerate(candidates, start=1):
        tried += 1
        normalized_candidate = normalize_model_parameters(model_id, candidate)
        trial_start = time.perf_counter()
        try:
            if should_isolate_model(model_id):
                output = run_isolated_fit_predict(
                    model_id,
                    normalized_candidate,
                    tune_train_times,
                    tune_train_values,
                    frequency,
                    validation_size,
                    covariates=tune_train_covariates,
                    future_covariates=tune_future_covariates,
                    feature_config=feature_config,
                )
                predictions = output.predictions[:validation_size]
            else:
                model = create_model(model_id, normalized_candidate)
                fit_model_instance(
                    model_id,
                    model,
                    tune_train_times,
                    tune_train_values,
                    frequency,
                    covariates=tune_train_covariates,
                    feature_config=feature_config,
                )
                predictions = predict_model_instance(
                    model_id,
                    model,
                    validation_size,
                    future_covariates=tune_future_covariates,
                ).predictions[:validation_size]
            metrics, metric_warnings = calculate_metrics(tune_test_values, predictions)
            warnings.extend(metric_warnings)
            mae = metrics.mae
            if mae is not None and (best_metric is None or mae < best_metric):
                best_metric = mae
                best_params = normalized_candidate
            trials.append(
                TuningTrial(
                    round=round_index,
                    params=normalized_candidate,
                    status="success",
                    metrics=metrics,
                    elapsedSeconds=round(time.perf_counter() - trial_start, 4),
                    selected=False,
                    message="评估成功。",
                )
            )
        except Exception as exc:
            warnings.append(f"{model_id} 候选参数 {normalized_candidate} 评估失败：{exc}")
            trials.append(
                TuningTrial(
                    round=round_index,
                    params=normalized_candidate,
                    status="failed",
                    metrics=None,
                    elapsedSeconds=round(time.perf_counter() - trial_start, 4),
                    selected=False,
                    message=str(exc),
                )
            )
        if progress_callback:
            best_text = "" if best_metric is None else f"，当前最佳 MAE {best_metric:.4f}"
            progress_callback(tried, len(candidates), f"已评估 {tried}/{len(candidates)} 组候选参数{best_text}。")
        if time.perf_counter() - start >= budget_seconds and tried >= 1:
            warnings.append(f"达到 {run_profile} 模式时间预算，已提前停止搜索。")
            stopped_early = tried < len(candidates)
            break

    selected_signature = tuple(sorted(best_params.items()))
    selected_marked = False
    for trial in trials:
        if trial.status != "success":
            continue
        if tuple(sorted(trial.params.items())) == selected_signature and not selected_marked:
            trial.selected = True
            selected_marked = True

    return ModelTuning(
        enabled=True,
        profile=run_profile,
        strategy=parameter_strategy,
        selectedParams=best_params,
        candidateCount=max(tried, 1),
        bestMetric=best_metric,
        tuningSeconds=round(time.perf_counter() - start, 4),
        candidateLimit=candidate_limit,
        timeBudgetSeconds=budget_seconds,
        validationSize=validation_size,
        stoppedEarly=stopped_early,
        trials=trials,
        warnings=warnings,
    )
