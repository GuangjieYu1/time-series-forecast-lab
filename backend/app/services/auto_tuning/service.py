from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel

from app.models.seasonal_naive import SEASONAL_PERIODS
from app.schemas import MetricValues, ModelTuning, TuningTrial
from app.services.covariate_flow import build_future_covariate_rows
from app.services.metrics import calculate_metrics
from app.services.model_executor import fit_model_instance, predict_model_instance, run_isolated_fit_predict, should_isolate_model
from app.services.model_registry import create_model, normalize_model_parameters


PROFILE_LIMITS = {"fast": 4, "balanced": 7, "accurate": 10}
PROFILE_BUDGET_SECONDS = {"fast": 3.0, "balanced": 8.0, "accurate": 16.0}
TREE_MODEL_IDS = {"xgboost", "lightgbm", "random_forest"}
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

class TuningProgressUpdate(BaseModel):
    completed: int
    total: int
    message: str
    phase: str = "trial"
    trialNumber: int | None = None
    status: str = "running"
    params: dict[str, Any] = {}
    currentMetric: float | None = None
    bestMetric: float | None = None
    tuningSeconds: float = 0.0
    strategyLabel: str | None = None
    sampler: str | None = None
    pruner: str | None = None


TuningProgressCallback = Callable[[TuningProgressUpdate], None]


def describe_tuning_profile(run_profile: str) -> dict[str, float | int]:
    profile = run_profile if run_profile in PROFILE_LIMITS else "balanced"
    return {
        "candidateLimit": PROFILE_LIMITS[profile],
        "timeBudgetSeconds": PROFILE_BUDGET_SECONDS[profile],
    }


def _strategy_metadata(
    model_id: str,
    *,
    parameter_strategy: str,
    run_profile: str,
    optuna_enabled: bool = False,
) -> tuple[str, str | None, str | None]:
    if parameter_strategy != "auto":
        return ("Default Parameters", None, None)
    if model_id in TREE_MODEL_IDS:
        if optuna_enabled:
            pruner = "Median Pruner" if run_profile == "fast" else "Successive Halving"
            return ("Optuna Optimization Engine", "TPE", pruner)
        return ("Transparent Candidate Search", "Candidate Queue", "Time Budget Stopper")
    if model_id == "timesfm":
        return ("Foundation Model Context Search", "Context / Normalize Sweep", "Budget Stopper")
    return ("Model-native Optimizer", "Built-in", None)


def _build_model_tuning(
    *,
    enabled: bool,
    profile: str,
    strategy: str,
    selected_params: dict[str, Any],
    candidate_count: int,
    best_metric: float | None,
    tuning_seconds: float,
    candidate_limit: int,
    time_budget_seconds: float,
    validation_size: int,
    stopped_early: bool,
    trials: list[TuningTrial],
    warnings: list[str],
    strategy_label: str,
    sampler: str | None,
    pruner: str | None,
) -> ModelTuning:
    return ModelTuning(
        enabled=enabled,
        profile=profile,
        strategy=strategy,
        strategyLabel=strategy_label,
        sampler=sampler,
        pruner=pruner,
        selectedParams=selected_params,
        candidateCount=candidate_count,
        bestMetric=best_metric,
        tuningSeconds=tuning_seconds,
        candidateLimit=candidate_limit,
        timeBudgetSeconds=time_budget_seconds,
        validationSize=validation_size,
        stoppedEarly=stopped_early,
        trials=trials,
        warnings=warnings,
    )


def _emit_tuning_progress(
    progress_callback: TuningProgressCallback | None,
    *,
    completed: int,
    total: int,
    message: str,
    phase: str,
    status: str,
    tuning_seconds: float,
    strategy_label: str,
    sampler: str | None,
    pruner: str | None,
    trial_number: int | None = None,
    params: dict[str, Any] | None = None,
    current_metric: float | None = None,
    best_metric: float | None = None,
) -> None:
    if not progress_callback:
        return
    progress_callback(
        TuningProgressUpdate(
            completed=completed,
            total=total,
            message=message,
            phase=phase,
            trialNumber=trial_number,
            status=status,
            params=params or {},
            currentMetric=current_metric,
            bestMetric=best_metric,
            tuningSeconds=tuning_seconds,
            strategyLabel=strategy_label,
            sampler=sampler,
            pruner=pruner,
        )
    )


def _try_import_optuna():
    try:
        import optuna  # type: ignore

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        return optuna
    except Exception:
        return None


def _tree_search_space(model_id: str, trial) -> dict[str, Any]:
    if model_id == "xgboost":
        return {
            "nEstimators": trial.suggest_int("nEstimators", 80, 420, step=20),
            "maxDepth": trial.suggest_int("maxDepth", 2, 8),
            "learningRate": trial.suggest_float("learningRate", 0.01, 0.25, log=True),
        }
    if model_id == "lightgbm":
        return {
            "nEstimators": trial.suggest_int("nEstimators", 120, 520, step=20),
            "numLeaves": trial.suggest_int("numLeaves", 15, 127, step=8),
            "learningRate": trial.suggest_float("learningRate", 0.01, 0.25, log=True),
        }
    if model_id == "random_forest":
        return {
            "nEstimators": trial.suggest_int("nEstimators", 80, 320, step=20),
            "maxDepth": trial.suggest_int("maxDepth", 4, 36, step=2),
            "minSamplesLeaf": trial.suggest_int("minSamplesLeaf", 1, 8),
        }
    return {}


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
    actual_values: list[float],
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
    metrics, _warnings = calculate_metrics(actual_values, output.predictions[:test_size])
    return metrics


def _resolve_tree_model_with_optuna(
    *,
    model_id: str,
    base: dict[str, Any],
    run_profile: str,
    random_seed: int,
    frequency: str,
    validation_size: int,
    candidate_limit: int,
    budget_seconds: float,
    tune_train_times: list[datetime],
    tune_train_values: list[float],
    tune_test_values: list[float],
    tune_train_covariates: list[dict[str, float]] | None,
    tune_future_covariates: list[dict[str, float]] | None,
    feature_config: dict[str, bool] | None,
    progress_callback: TuningProgressCallback | None,
) -> ModelTuning | None:
    optuna = _try_import_optuna()
    if optuna is None:
        return None

    strategy_label, sampler_name, pruner_name = _strategy_metadata(
        model_id,
        parameter_strategy="auto",
        run_profile=run_profile,
        optuna_enabled=True,
    )
    warnings: list[str] = []
    trials: list[TuningTrial] = []
    best_metric: float | None = None
    best_params = base
    start = time.perf_counter()

    pruner = (
        optuna.pruners.MedianPruner(n_startup_trials=1, n_warmup_steps=0)
        if run_profile == "fast"
        else optuna.pruners.SuccessiveHalvingPruner(min_resource=1, reduction_factor=3 if run_profile == "balanced" else 2)
    )
    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=random_seed),
        pruner=pruner,
    )

    _emit_tuning_progress(
        progress_callback,
        completed=0,
        total=candidate_limit,
        message=f"正在使用 Optuna（TPE）搜索参数，共 {candidate_limit} 次试验预算。",
        phase="queued",
        status="running",
        tuning_seconds=0.0,
        strategy_label=strategy_label,
        sampler=sampler_name,
        pruner=pruner_name,
    )

    def objective(trial) -> float:
        nonlocal best_metric, best_params
        trial_number = int(trial.number) + 1
        params = normalize_model_parameters(model_id, {**base, **_tree_search_space(model_id, trial)})
        _emit_tuning_progress(
            progress_callback,
            completed=max(trial_number - 1, 0),
            total=candidate_limit,
            message=f"开始评估 Optuna Trial #{trial_number}。",
            phase="trial",
            status="running",
            tuning_seconds=round(time.perf_counter() - start, 4),
            strategy_label=strategy_label,
            sampler=sampler_name,
            pruner=pruner_name,
            trial_number=trial_number,
            params=params,
            best_metric=best_metric,
        )
        trial_start = time.perf_counter()
        try:
            metrics = _evaluate_candidate(
                model_id,
                params,
                tune_train_times,
                tune_train_values,
                tune_test_values,
                frequency,
                validation_size,
                train_covariates=tune_train_covariates,
                future_covariates=tune_future_covariates,
                feature_config=feature_config,
            )
            mae = metrics.mae
            metric_value = float(mae) if mae is not None else float("inf")
            trial.report(metric_value, step=1)
            if trial.should_prune():
                trials.append(
                    TuningTrial(
                        round=trial_number,
                        params=params,
                        status="pruned",
                        metrics=metrics,
                        elapsedSeconds=round(time.perf_counter() - trial_start, 4),
                        selected=False,
                        message="该组参数被剪枝，未继续保留。",
                    )
                )
                _emit_tuning_progress(
                    progress_callback,
                    completed=trial_number,
                    total=candidate_limit,
                    message=f"Trial #{trial_number} 被剪枝。",
                    phase="trial",
                    status="pruned",
                    tuning_seconds=round(time.perf_counter() - start, 4),
                    strategy_label=strategy_label,
                    sampler=sampler_name,
                    pruner=pruner_name,
                    trial_number=trial_number,
                    params=params,
                    current_metric=mae,
                    best_metric=best_metric,
                )
                raise optuna.TrialPruned("pruned by study")
            if mae is not None and (best_metric is None or mae < best_metric):
                best_metric = mae
                best_params = params
            trials.append(
                TuningTrial(
                    round=trial_number,
                    params=params,
                    status="success",
                    metrics=metrics,
                    elapsedSeconds=round(time.perf_counter() - trial_start, 4),
                    selected=False,
                    message="Optuna 评估成功。",
                )
            )
            _emit_tuning_progress(
                progress_callback,
                completed=trial_number,
                total=candidate_limit,
                message=f"Trial #{trial_number} 评估成功。",
                phase="trial",
                status="success",
                tuning_seconds=round(time.perf_counter() - start, 4),
                strategy_label=strategy_label,
                sampler=sampler_name,
                pruner=pruner_name,
                trial_number=trial_number,
                params=params,
                current_metric=mae,
                best_metric=best_metric,
            )
            return metric_value
        except optuna.TrialPruned:
            raise
        except Exception as exc:
            warnings.append(f"{model_id} Trial #{trial_number} 评估失败：{exc}")
            trials.append(
                TuningTrial(
                    round=trial_number,
                    params=params,
                    status="failed",
                    metrics=None,
                    elapsedSeconds=round(time.perf_counter() - trial_start, 4),
                    selected=False,
                    message=str(exc),
                )
            )
            _emit_tuning_progress(
                progress_callback,
                completed=trial_number,
                total=candidate_limit,
                message=f"Trial #{trial_number} 评估失败：{exc}",
                phase="trial",
                status="failed",
                tuning_seconds=round(time.perf_counter() - start, 4),
                strategy_label=strategy_label,
                sampler=sampler_name,
                pruner=pruner_name,
                trial_number=trial_number,
                params=params,
                best_metric=best_metric,
            )
            raise

    try:
        study.optimize(
            objective,
            n_trials=candidate_limit,
            timeout=budget_seconds,
            catch=(Exception,),
        )
    except Exception as exc:
        warnings.append(f"Optuna 搜索异常终止：{exc}")

    success_trials = [trial for trial in trials if trial.status == "success" and trial.metrics and trial.metrics.mae is not None]
    if success_trials:
        selected_signature = tuple(sorted(best_params.items()))
        selected_marked = False
        for trial in success_trials:
            if tuple(sorted(trial.params.items())) == selected_signature and not selected_marked:
                trial.selected = True
                selected_marked = True
        candidate_count = len(trials) if trials else len(success_trials)
        stopped_early = bool(candidate_count < candidate_limit and time.perf_counter() - start >= budget_seconds)
        if stopped_early:
            warnings.append(f"达到 {run_profile} 模式时间预算，已提前结束 Optuna 搜索。")
        return _build_model_tuning(
            enabled=True,
            profile=run_profile,
            strategy="auto",
            selected_params=best_params,
            candidate_count=max(candidate_count, 1),
            best_metric=best_metric,
            tuning_seconds=round(time.perf_counter() - start, 4),
            candidate_limit=candidate_limit,
            time_budget_seconds=budget_seconds,
            validation_size=validation_size,
            stopped_early=stopped_early,
            trials=trials,
            warnings=warnings,
            strategy_label=strategy_label,
            sampler=sampler_name,
            pruner=pruner_name,
        )
    return None


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
    base = normalize_model_parameters(model_id, requested_parameters)
    strategy_profile = describe_tuning_profile(run_profile)
    candidate_limit = int(strategy_profile["candidateLimit"])
    budget_seconds = float(strategy_profile["timeBudgetSeconds"])
    default_strategy_label, default_sampler, default_pruner = _strategy_metadata(
        model_id,
        parameter_strategy=parameter_strategy,
        run_profile=run_profile,
    )
    if parameter_strategy != "auto":
        return _build_model_tuning(
            enabled=False,
            profile=run_profile,
            strategy=parameter_strategy,
            selected_params=base,
            candidate_count=1,
            best_metric=None,
            tuning_seconds=0.0,
            candidate_limit=1,
            time_budget_seconds=0.0,
            validation_size=0,
            stopped_early=False,
            trials=[],
            warnings=[],
            strategy_label=default_strategy_label,
            sampler=default_sampler,
            pruner=default_pruner,
        )

    if model_id not in SUPPORTED_AUTO_TUNING_MODELS:
        return _build_model_tuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selected_params=base,
            candidate_count=1,
            best_metric=None,
            tuning_seconds=0.0,
            candidate_limit=1,
            time_budget_seconds=0.0,
            validation_size=0,
            stopped_early=False,
            trials=[],
            warnings=[f"{model_id} 暂不支持自动调参，已回退到当前参数。"],
            strategy_label=default_strategy_label,
            sampler=default_sampler,
            pruner=default_pruner,
        )

    if len(train_values) < max(18, test_size * 3):
        return _build_model_tuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selected_params=base,
            candidate_count=1,
            best_metric=None,
            tuning_seconds=0.0,
            candidate_limit=candidate_limit,
            time_budget_seconds=budget_seconds,
            validation_size=0,
            stopped_early=False,
            trials=[],
            warnings=["训练样本不足，自动调参已跳过并回退到当前参数。"],
            strategy_label=default_strategy_label,
            sampler=default_sampler,
            pruner=default_pruner,
        )

    validation_size = min(max(test_size, 4), max(4, len(train_values) // 4))
    tune_train_times = train_times[:-validation_size]
    tune_train_values = train_values[:-validation_size]
    tune_test_values = train_values[-validation_size:]
    tune_train_covariates = train_covariates[:-validation_size] if train_covariates else None
    observed_validation_covariates = train_covariates[-validation_size:] if train_covariates else future_covariates
    covariate_columns = list(train_covariates[0].keys()) if train_covariates else list(future_covariates[0].keys()) if future_covariates else []
    tune_future_covariates = build_future_covariate_rows(
        covariate_columns=covariate_columns,
        history_rows=tune_train_covariates,
        observed_future_rows=observed_validation_covariates,
        future_times=train_times[-validation_size:],
    )

    if len(tune_train_values) < 12:
        return _build_model_tuning(
            enabled=True,
            profile=run_profile,
            strategy=parameter_strategy,
            selected_params=base,
            candidate_count=1,
            best_metric=None,
            tuning_seconds=0.0,
            candidate_limit=candidate_limit,
            time_budget_seconds=budget_seconds,
            validation_size=validation_size,
            stopped_early=False,
            trials=[],
            warnings=["调参切分后训练样本不足，已回退到当前参数。"],
            strategy_label=default_strategy_label,
            sampler=default_sampler,
            pruner=default_pruner,
        )

    if model_id in TREE_MODEL_IDS:
        optuna_result = _resolve_tree_model_with_optuna(
            model_id=model_id,
            base=base,
            run_profile=run_profile,
            random_seed=random_seed,
            frequency=frequency,
            validation_size=validation_size,
            candidate_limit=candidate_limit,
            budget_seconds=budget_seconds,
            tune_train_times=tune_train_times,
            tune_train_values=tune_train_values,
            tune_test_values=tune_test_values,
            tune_train_covariates=tune_train_covariates,
            tune_future_covariates=tune_future_covariates,
            feature_config=feature_config,
            progress_callback=progress_callback,
        )
        if optuna_result is not None:
            return optuna_result

    candidates = _dedupe_candidates(
        model_id,
        [base, *_candidate_grid(model_id, base, frequency=frequency, series_length=len(tune_train_values))],
        frequency=frequency,
        series_length=len(tune_train_values),
    )
    candidates = candidates[:candidate_limit]
    warnings: list[str] = []
    if model_id in TREE_MODEL_IDS and _try_import_optuna() is None:
        warnings.append("当前环境未安装 Optuna，树模型自动优化已回退到候选队列搜索。")
    _emit_tuning_progress(
        progress_callback,
        completed=0,
        total=len(candidates),
        message=f"正在自动优化参数，共 {len(candidates)} 组候选。",
        phase="queued",
        status="running",
        tuning_seconds=0.0,
        strategy_label=default_strategy_label,
        sampler=default_sampler,
        pruner=default_pruner,
    )

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
        _emit_tuning_progress(
            progress_callback,
            completed=max(tried - 1, 0),
            total=len(candidates),
            message=f"开始评估候选 #{round_index}。",
            phase="trial",
            status="running",
            tuning_seconds=round(time.perf_counter() - start, 4),
            strategy_label=default_strategy_label,
            sampler=default_sampler,
            pruner=default_pruner,
            trial_number=round_index,
            params=normalized_candidate,
            best_metric=best_metric,
        )
        try:
            metrics = _evaluate_candidate(
                model_id,
                normalized_candidate,
                tune_train_times,
                tune_train_values,
                tune_test_values,
                frequency,
                validation_size,
                train_covariates=tune_train_covariates,
                future_covariates=tune_future_covariates,
                feature_config=feature_config,
            )
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
            _emit_tuning_progress(
                progress_callback,
                completed=tried,
                total=len(candidates),
                message=f"候选 #{round_index} 评估成功。",
                phase="trial",
                status="success",
                tuning_seconds=round(time.perf_counter() - start, 4),
                strategy_label=default_strategy_label,
                sampler=default_sampler,
                pruner=default_pruner,
                trial_number=round_index,
                params=normalized_candidate,
                current_metric=mae,
                best_metric=best_metric,
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
            _emit_tuning_progress(
                progress_callback,
                completed=tried,
                total=len(candidates),
                message=f"候选 #{round_index} 评估失败：{exc}",
                phase="trial",
                status="failed",
                tuning_seconds=round(time.perf_counter() - start, 4),
                strategy_label=default_strategy_label,
                sampler=default_sampler,
                pruner=default_pruner,
                trial_number=round_index,
                params=normalized_candidate,
                best_metric=best_metric,
            )
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

    return _build_model_tuning(
        enabled=True,
        profile=run_profile,
        strategy=parameter_strategy,
        selected_params=best_params,
        candidate_count=max(tried, 1),
        best_metric=best_metric,
        tuning_seconds=round(time.perf_counter() - start, 4),
        candidate_limit=candidate_limit,
        time_budget_seconds=budget_seconds,
        validation_size=validation_size,
        stopped_early=stopped_early,
        trials=trials,
        warnings=warnings,
        strategy_label=default_strategy_label,
        sampler=default_sampler,
        pruner=default_pruner,
    )
