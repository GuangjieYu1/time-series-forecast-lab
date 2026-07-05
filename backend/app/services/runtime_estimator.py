from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.models import ExperimentRecord
from app.schemas import RuntimeEstimateItem, RuntimeEstimateRequest, RuntimeEstimateResponse
from app.services.model_registry import MODEL_CAPABILITIES


DeviceKind = Literal["cpu", "gpu"]

TREE_MODEL_IDS = {"xgboost", "lightgbm", "random_forest"}

BASELINE_SECONDS: dict[str, float] = {
    "naive": 0.6,
    "seasonal_naive": 0.9,
    "moving_average": 1.2,
    "ets": 4.5,
    "arima": 18.0,
    "prophet": 28.0,
    "xgboost": 30.0,
    "lightgbm": 24.0,
    "random_forest": 150.0,
    "timesfm": 35.0,
}

ROW_EXPONENT: dict[str, float] = {
    "naive": 0.18,
    "seasonal_naive": 0.22,
    "moving_average": 0.28,
    "ets": 0.48,
    "arima": 0.58,
    "prophet": 0.62,
    "xgboost": 0.72,
    "lightgbm": 0.68,
    "random_forest": 0.8,
    "timesfm": 0.55,
}

PROFILE_FACTOR = {"fast": 0.72, "balanced": 1.0, "accurate": 1.32}

AUTO_TUNING_FACTOR: dict[str, float] = {
    "naive": 1.0,
    "seasonal_naive": 1.15,
    "moving_average": 1.18,
    "ets": 1.35,
    "arima": 1.55,
    "prophet": 1.7,
    "xgboost": 2.1,
    "lightgbm": 1.9,
    "random_forest": 2.45,
    "timesfm": 1.35,
}


@dataclass
class RuntimeHistorySample:
    model_id: str
    row_count: int
    covariate_count: int
    feature_count: int
    run_profile: str
    parameter_strategy: str
    device_kind: DeviceKind
    seconds: float


def estimate_runtime(request: RuntimeEstimateRequest, db: Session) -> RuntimeEstimateResponse:
    history = _load_history_samples(db)
    items: list[RuntimeEstimateItem] = []
    for model_id in request.selectedModels:
        capability = MODEL_CAPABILITIES.get(model_id)
        if capability is None:
            continue
        items.append(_estimate_model_runtime(request, model_id, history))
    items.sort(key=lambda item: item.estimatedSeconds)
    return RuntimeEstimateResponse(models=items)


def _estimate_model_runtime(
    request: RuntimeEstimateRequest,
    model_id: str,
    history: list[RuntimeHistorySample],
) -> RuntimeEstimateItem:
    capability = MODEL_CAPABILITIES[model_id]
    device_kind = _compute_target(model_id, request.device)
    row_count = max(request.rowCount, 1)
    covariate_count = max(request.covariateCount, 0)
    feature_count = _estimate_feature_count(model_id, covariate_count, request.featureConfig.model_dump())
    relevant = [sample for sample in history if sample.model_id == model_id and sample.seconds > 0]

    if relevant:
        weighted_total = 0.0
        weight_sum = 0.0
        best_similarity = 0.0
        for sample in relevant:
            similarity = _similarity(
                sample,
                row_count=row_count,
                covariate_count=covariate_count,
                feature_count=feature_count,
                run_profile=request.runProfile,
                parameter_strategy=request.parameterStrategy,
                device_kind=device_kind,
            )
            best_similarity = max(best_similarity, similarity)
            adjusted = sample.seconds
            adjusted *= ((row_count + 1) / (sample.row_count + 1)) ** ROW_EXPONENT.get(model_id, 0.65)
            adjusted *= _feature_factor(model_id, covariate_count, feature_count) / _feature_factor(
                model_id,
                sample.covariate_count,
                sample.feature_count,
            )
            adjusted *= PROFILE_FACTOR.get(request.runProfile, 1.0) / PROFILE_FACTOR.get(sample.run_profile, 1.0)
            adjusted *= _strategy_factor(model_id, request.parameterStrategy) / _strategy_factor(model_id, sample.parameter_strategy)
            adjusted *= _device_factor(model_id, device_kind) / _device_factor(model_id, sample.device_kind)
            weight = 0.35 + similarity
            weighted_total += adjusted * weight
            weight_sum += weight
        per_target_seconds = weighted_total / max(weight_sum, 1e-6)
        confidence = "high" if len(relevant) >= 4 and best_similarity >= 0.72 else "medium"
    else:
        per_target_seconds = _fallback_seconds(
            model_id=model_id,
            row_count=row_count,
            covariate_count=covariate_count,
            feature_count=feature_count,
            run_profile=request.runProfile,
            parameter_strategy=request.parameterStrategy,
            device_kind=device_kind,
        )
        confidence = "low"

    auxiliary_factor = 1.0 + request.unknownFutureForecastCount * 0.35 + request.perPrimaryModelCovariateCount * 0.8
    estimated_seconds = round(max(0.2, per_target_seconds) * auxiliary_factor * max(request.targetCount, 1), 1)
    descriptor = [
        f"{row_count} timestamps",
        f"{covariate_count} covariates" if covariate_count else "univariate",
        f"{feature_count} derived features" if feature_count > 1 else "minimal features",
        f"{request.targetCount} target{'s' if request.targetCount > 1 else ''}",
    ]
    if request.unknownFutureForecastCount:
        descriptor.append(f"{request.unknownFutureForecastCount} unknown-future forecasts")
    if request.perPrimaryModelCovariateCount:
        descriptor.append(f"{request.perPrimaryModelCovariateCount} per-model covariates")
    if request.parameterStrategy == "auto":
        descriptor.append("auto tuning")
    if relevant:
        descriptor.append(f"{len(relevant)} history samples")
    return RuntimeEstimateItem(
        id=model_id,
        name=capability.name,
        estimatedSeconds=estimated_seconds,
        confidence=confidence,
        reason=" · ".join(descriptor),
        sampleCount=len(relevant),
        computeTarget=device_kind,
    )


def _load_history_samples(db: Session) -> list[RuntimeHistorySample]:
    records = db.query(ExperimentRecord).order_by(ExperimentRecord.created_at.desc()).limit(200).all()
    samples: list[RuntimeHistorySample] = []
    for record in records:
        try:
            config = json.loads(record.config_json or "{}")
            profiles = json.loads(record.data_profile_json or "{}").get("targets") or []
            model_logs = json.loads(record.model_logs_json or "[]")
            manifest = json.loads(record.manifest_json) if record.manifest_json else {}
            device = _normalize_device_kind(((manifest.get("environment") or {}).get("device")))
            profile_by_target = {
                str(profile.get("targetColumn")): profile
                for profile in profiles
                if isinstance(profile, dict) and profile.get("targetColumn")
            }
            for model_log in model_logs:
                if not isinstance(model_log, dict) or model_log.get("status") != "success":
                    continue
                model_id = str(model_log.get("modelId") or "")
                if model_id not in MODEL_CAPABILITIES:
                    continue
                target_profile = profile_by_target.get(str(model_log.get("targetColumn")))
                if not target_profile:
                    continue
                runtime = model_log.get("runtime") or {}
                tuning = model_log.get("tuning") or {}
                seconds = float(runtime.get("fitSeconds") or 0) + float(runtime.get("predictSeconds") or 0) + float(tuning.get("tuningSeconds") or 0)
                if seconds <= 0:
                    continue
                covariate_columns = target_profile.get("covariateColumns") or []
                feature_config = target_profile.get("featureConfig") or config.get("featureConfig") or {}
                samples.append(
                    RuntimeHistorySample(
                        model_id=model_id,
                        row_count=max(len(target_profile.get("history") or []), 1),
                        covariate_count=len(covariate_columns),
                        feature_count=_estimate_feature_count(model_id, len(covariate_columns), feature_config),
                        run_profile=str(tuning.get("profile") or config.get("runProfile") or "balanced"),
                        parameter_strategy=str(tuning.get("strategy") or config.get("parameterStrategy") or "default"),
                        device_kind=device,
                        seconds=seconds,
                    )
                )
        except Exception:
            continue
    return samples


def _estimate_feature_count(model_id: str, covariate_count: int, feature_config: dict[str, Any]) -> int:
    if model_id in {"naive", "seasonal_naive", "moving_average", "ets", "arima", "prophet"}:
        return 1
    lag_features = 6 if feature_config.get("lagFeatures", True) else 0
    rolling_features = 10 if feature_config.get("rollingFeatures", True) else 0
    calendar_features = 7 if feature_config.get("calendarFeatures", True) else 0
    covariate_features = covariate_count if feature_config.get("covariates", True) else 0
    if model_id == "timesfm":
        return max(1, 1 + covariate_features)
    return max(1, lag_features + rolling_features + calendar_features + covariate_features)


def _normalize_device_kind(device: Any) -> DeviceKind:
    text = str(device or "").lower()
    if any(token in text for token in ("cuda", "gpu", "nvidia", "mps")):
        return "gpu"
    return "cpu"


def _compute_target(model_id: str, device: str) -> DeviceKind:
    capability = MODEL_CAPABILITIES[model_id]
    if capability.requiresGpu and _normalize_device_kind(device) == "gpu":
        return "gpu"
    return "cpu"


def _feature_factor(model_id: str, covariate_count: int, feature_count: int) -> float:
    if model_id in TREE_MODEL_IDS:
        return 1.0 + min(4.0, feature_count / 45.0 + covariate_count / 180.0)
    if model_id == "timesfm":
        return 1.0 + min(1.8, covariate_count / 220.0 + feature_count / 160.0)
    return 1.0


def _strategy_factor(model_id: str, parameter_strategy: str) -> float:
    if parameter_strategy != "auto":
        return 1.0
    return AUTO_TUNING_FACTOR.get(model_id, 1.4)


def _device_factor(model_id: str, device_kind: DeviceKind) -> float:
    if model_id == "timesfm":
        return 0.72 if device_kind == "gpu" else 1.65
    return 1.0


def _fallback_seconds(
    *,
    model_id: str,
    row_count: int,
    covariate_count: int,
    feature_count: int,
    run_profile: str,
    parameter_strategy: str,
    device_kind: DeviceKind,
) -> float:
    seconds = BASELINE_SECONDS.get(model_id, 20.0)
    seconds *= (max(row_count, 1) / 1_000) ** ROW_EXPONENT.get(model_id, 0.65)
    seconds *= _feature_factor(model_id, covariate_count, feature_count)
    seconds *= PROFILE_FACTOR.get(run_profile, 1.0)
    seconds *= _strategy_factor(model_id, parameter_strategy)
    seconds *= _device_factor(model_id, device_kind)
    return seconds


def _similarity(
    sample: RuntimeHistorySample,
    *,
    row_count: int,
    covariate_count: int,
    feature_count: int,
    run_profile: str,
    parameter_strategy: str,
    device_kind: DeviceKind,
) -> float:
    row_gap = abs(math.log((row_count + 1) / (sample.row_count + 1)))
    covariate_gap = abs(covariate_count - sample.covariate_count) / max(16.0, float(max(covariate_count, sample.covariate_count, 1)))
    feature_gap = abs(feature_count - sample.feature_count) / max(8.0, float(max(feature_count, sample.feature_count, 1)))
    score = row_gap * 0.55 + covariate_gap * 0.25 + feature_gap * 0.2
    if sample.run_profile != run_profile:
        score += 0.18
    if sample.parameter_strategy != parameter_strategy:
        score += 0.28
    if sample.device_kind != device_kind:
        score += 0.12
    return 1.0 / (1.0 + score)
