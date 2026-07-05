from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from app.schemas import (
    RuntimeFeatureColumnProfile,
    RuntimeFeatureDataProfile,
    RuntimeFeatureFactorySummary,
    RuntimeFeaturePipelineStep,
    RuntimeFeaturePipelineTarget,
    RuntimeFeatureSelectionItem,
    RuntimeFeatureVisualization,
    RuntimeFeatureVisualizationMarker,
    RuntimeFeatureSelectionSummary,
)
from app.services.covariate_flow import canonical_covariate_name
from app.services.feature_step_catalog import feature_step_description
from app.schemas import HolidayConfig
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES, build_holiday_features


FEATURE_MODEL_IDS = {"xgboost", "lightgbm", "random_forest"}
DEFAULT_FEATURE_CONFIG = {
    "lagFeatures": True,
    "rollingFeatures": True,
    "calendarFeatures": True,
    "holidayFeatures": True,
    "covariates": True,
}


@dataclass
class PreparedFeatureMatrix:
    featureValues: np.ndarray
    targets: np.ndarray
    featureNames: list[str]
    times: list[datetime]
    values: list[float]
    frequency: str
    covariates: list[dict[str, float]]
    featureConfig: dict[str, bool]
    startIndex: int

    def slice_history(self, end_index: int) -> "PreparedFeatureMatrix":
        bounded_end = min(max(int(end_index), 0), len(self.values))
        matrix_end = max(bounded_end - self.startIndex, 0)
        return PreparedFeatureMatrix(
            featureValues=self.featureValues[:matrix_end],
            targets=self.targets[:matrix_end],
            featureNames=list(self.featureNames),
            times=self.times[:bounded_end],
            values=self.values[:bounded_end],
            frequency=self.frequency,
            covariates=self.covariates[:bounded_end] if self.covariates else [],
            featureConfig=dict(self.featureConfig),
            startIndex=self.startIndex,
        )


@dataclass
class FeatureFactoryResult:
    prepared: PreparedFeatureMatrix | None
    pipeline: RuntimeFeaturePipelineTarget
    error: str | None = None


FeatureProgressCallback = Callable[[RuntimeFeaturePipelineTarget], None]


STEP_SPECS = [
    ("source_alignment", "源数据对齐", None),
    ("covariate_loader", "协变量加载器", "covariate_loader"),
    ("calendar_generator", "日历特征生成器", "calendar_generator"),
    ("holiday_generator", "节假日生成器", "holiday_generator"),
    ("lag_generator", "滞后特征生成器", "lag_generator"),
    ("rolling_generator", "滚动统计生成器", "rolling_generator"),
    ("feature_merge", "特征合并", None),
    ("leakage_guard", "数据泄漏防护", None),
    ("feature_selection", "特征筛选", None),
    ("matrix_ready", "训练矩阵就绪", None),
]


def has_feature_consumers(selected_model_ids: list[str]) -> bool:
    return any(model_id in FEATURE_MODEL_IDS for model_id in selected_model_ids)


def build_feature_factory(
    *,
    pipeline: RuntimeFeaturePipelineTarget,
    times: list[datetime],
    values: list[float],
    frequency: str,
    covariates: list[dict[str, float]] | None,
    feature_config: dict[str, bool] | None,
    selected_model_ids: list[str],
    holiday_config: dict | HolidayConfig | None = None,
    progress_callback: FeatureProgressCallback | None = None,
) -> FeatureFactoryResult:
    target = pipeline.model_copy(deep=True)
    target.traceMode = "live"
    target.status = "running"
    target.progressPercent = 0
    target.currentStepId = None
    target.steps = [
        RuntimeFeaturePipelineStep(
            id=step_id,
            sequence=index + 1,
            label=label,
            description=feature_step_description(step_id),
            machineId=machine_id,
        )
        for index, (step_id, label, machine_id) in enumerate(STEP_SPECS)
    ]

    normalized_config = dict(DEFAULT_FEATURE_CONFIG)
    if feature_config:
        normalized_config.update({key: bool(value) for key, value in feature_config.items() if key in normalized_config})
    normalized_times = list(times)
    normalized_values = np.asarray(values, dtype=float)
    normalized_covariates = list(covariates or [])
    normalized_holiday_config = holiday_config if isinstance(holiday_config, HolidayConfig) else HolidayConfig.model_validate(holiday_config or {})
    time_start = normalized_times[0].isoformat() if normalized_times else None
    time_end = normalized_times[-1].isoformat() if normalized_times else None
    sampled_indexes = list(range(0, len(normalized_values), max(1, len(normalized_values) // 16)))[:16]
    for item in target.steps:
        item.visualization = RuntimeFeatureVisualization(
            kind=item.id,
            timeStart=time_start,
            timeEnd=time_end,
            sampleValues=[float(normalized_values[index]) for index in sampled_indexes],
            sampleLabels=[normalized_times[index].isoformat() for index in sampled_indexes],
            windowSize=7 if item.id in {"lag_generator", "rolling_generator"} else None,
        )
    consumers = [model_id for model_id in selected_model_ids if model_id in FEATURE_MODEL_IDS]
    family_matrices: dict[str, tuple[np.ndarray, list[str]]] = {}
    merged_matrix: np.ndarray | None = None
    merged_names: list[str] = []
    selected_matrix: np.ndarray | None = None
    selected_names: list[str] = []
    start_index = 7 if normalized_config["lagFeatures"] or normalized_config["rollingFeatures"] else 1

    def emit() -> None:
        resolved = sum(step.status in {"completed", "skipped", "failed"} for step in target.steps)
        target.progressPercent = int((resolved / max(len(target.steps), 1)) * 100)
        if progress_callback:
            progress_callback(target.model_copy(deep=True))

    def machine_update(step: RuntimeFeaturePipelineStep) -> None:
        if not step.machineId:
            return
        for machine in target.machines:
            if machine.id != step.machineId:
                continue
            machine.status = step.status
            machine.durationSeconds = step.elapsedSeconds
            machine.generatedFeatures = list(step.generatedFeatures)
            machine.warnings = list(step.warnings)
            machine.enabled = step.status != "skipped"
            machine.summary = step.outputSummary or step.skipReason or machine.summary
            break

    def begin(step_id: str, input_summary: str, input_profile: RuntimeFeatureDataProfile | None = None) -> RuntimeFeaturePipelineStep:
        step = next(item for item in target.steps if item.id == step_id)
        step.status = "running"
        step.progressPercent = 5
        step.startedAt = datetime.now(timezone.utc)
        step.inputSummary = input_summary
        step.inputProfile = input_profile
        target.currentStepId = step_id
        emit()
        return step

    def complete(
        step: RuntimeFeaturePipelineStep,
        *,
        output_summary: str,
        output_profile: RuntimeFeatureDataProfile | None = None,
        generated_features: list[str] | None = None,
        selected_features: list[str] | None = None,
        dropped_features: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        finished = datetime.now(timezone.utc)
        step.status = "completed"
        step.progressPercent = 100
        step.finishedAt = finished
        step.elapsedSeconds = round(max((finished - (step.startedAt or finished)).total_seconds(), 0.0), 6)
        step.outputSummary = output_summary
        step.outputProfile = output_profile
        step.generatedFeatures = list(generated_features or [])
        step.selectedFeatures = list(selected_features or [])
        step.droppedFeatures = list(dropped_features or [])
        step.warnings = list(warnings or [])
        machine_update(step)
        emit()

    def skip(step_id: str, reason: str, input_summary: str = "") -> None:
        now = datetime.now(timezone.utc)
        step = next(item for item in target.steps if item.id == step_id)
        step.status = "skipped"
        step.progressPercent = 100
        step.startedAt = now
        step.finishedAt = now
        step.elapsedSeconds = 0.0
        step.inputSummary = input_summary
        step.outputSummary = reason
        step.skipReason = reason
        machine_update(step)
        emit()

    def fail(step: RuntimeFeaturePipelineStep, exc: Exception) -> FeatureFactoryResult:
        finished = datetime.now(timezone.utc)
        step.status = "failed"
        step.progressPercent = 100
        step.finishedAt = finished
        step.elapsedSeconds = round(max((finished - (step.startedAt or finished)).total_seconds(), 0.0), 6)
        step.error = str(exc)
        step.outputSummary = "Feature step failed."
        machine_update(step)
        target.status = "failed"
        target.currentStepId = step.id
        target.warnings = [*target.warnings, str(exc)]
        for downstream in target.steps:
            if downstream.sequence <= step.sequence or downstream.status != "pending":
                continue
            downstream.status = "skipped"
            downstream.progressPercent = 100
            downstream.skipReason = f"Upstream step {step.label} failed."
            downstream.outputSummary = downstream.skipReason
        emit()
        return FeatureFactoryResult(prepared=None, pipeline=target, error=str(exc))

    source_profile = _profile_matrix(normalized_values.reshape(-1, 1), [target.targetColumn])
    step = begin("source_alignment", f"Validate {len(normalized_values)} ordered target points.", source_profile)
    try:
        if len(normalized_times) != len(normalized_values):
            raise ValueError("Time and target arrays are not aligned.")
        if len(normalized_values) < 2:
            raise ValueError("At least two points are required for feature engineering.")
        if not np.isfinite(normalized_values).all():
            raise ValueError("Target values contain NaN or infinite values after cleaning.")
        if any(left >= right for left, right in zip(normalized_times, normalized_times[1:])):
            raise ValueError("Feature Factory requires a strictly increasing time axis.")
        complete(step, output_summary="Time axis and target values are aligned.", output_profile=source_profile)
    except Exception as exc:
        return fail(step, exc)

    if normalized_config["covariates"] and normalized_covariates:
        step = begin("covariate_loader", f"Load {len(normalized_covariates)} aligned covariate rows.", source_profile)
        try:
            if len(normalized_covariates) != len(normalized_values):
                raise ValueError("Covariate rows must align one-to-one with target history.")
            covariate_names = [str(name) for name in normalized_covariates[0].keys()]
            covariate_matrix = np.asarray(
                [[float(row.get(name, 0.0)) for name in covariate_names] for row in normalized_covariates],
                dtype=float,
            )
            family_matrices["covariates"] = (covariate_matrix, covariate_names)
            profile = _profile_matrix(covariate_matrix, covariate_names)
            complete(
                step,
                output_summary=f"Loaded {len(covariate_names)} covariates without persisting row values.",
                output_profile=profile,
                generated_features=covariate_names,
            )
        except Exception as exc:
            return fail(step, exc)
    else:
        skip("covariate_loader", "No enabled user covariates.", "Covariate feature family is disabled or empty.")

    if normalized_config["calendarFeatures"]:
        step = begin("calendar_generator", "Generate deterministic fields from the target timestamp.", source_profile)
        started = time.perf_counter()
        try:
            calendar_names = ["time_index", "day_of_week", "month"]
            calendar_matrix = np.asarray(
                [[float(index), float(value.weekday()), float(value.month)] for index, value in enumerate(normalized_times)],
                dtype=float,
            )
            family_matrices["calendar"] = (calendar_matrix, calendar_names)
            complete(
                step,
                output_summary="Generated index, weekday and month features.",
                output_profile=_profile_matrix(calendar_matrix, calendar_names),
                generated_features=calendar_names,
            )
            step.elapsedSeconds = round(time.perf_counter() - started, 6)
            machine_update(step)
        except Exception as exc:
            return fail(step, exc)
    else:
        skip("calendar_generator", "Calendar features are disabled by featureConfig.")

    if normalized_config["holidayFeatures"] and normalized_holiday_config.enabled:
        step = begin("holiday_generator", f"生成 {normalized_holiday_config.countryCode} 节假日特征。", source_profile)
        try:
            holiday_result = build_holiday_features(normalized_times, frequency, normalized_holiday_config)
            holiday_names = [name for name in HOLIDAY_FEATURE_NAMES if name in family_matrices.get("covariates", (np.empty((0, 0)), []))[1]]
            if step.visualization:
                step.visualization.markers = holiday_result.markers
            complete(
                step,
                output_summary=(f"生成 {len(holiday_names)} 个节假日特征，区间内识别 {len(holiday_result.markers)} 个节假日。" if holiday_result.markers else f"生成 {len(holiday_names)} 个节假日特征；当前区间没有节假日。"),
                generated_features=holiday_names or holiday_result.names,
            )
        except Exception as exc:
            return fail(step, exc)
    else:
        skip("holiday_generator", "节假日特征已在配置中关闭。")

    if normalized_config["lagFeatures"]:
        step = begin("lag_generator", "Generate target lags using prior observations only.", source_profile)
        try:
            lag_names = ["lag_1", "lag_2", "lag_3", "lag_7"]
            lag_matrix = np.full((len(normalized_values), len(lag_names)), np.nan, dtype=float)
            for column_index, offset in enumerate((1, 2, 3, 7)):
                lag_matrix[offset:, column_index] = normalized_values[:-offset]
            family_matrices["lag"] = (lag_matrix, lag_names)
            complete(
                step,
                output_summary="Generated lag_1, lag_2, lag_3 and lag_7 from strictly prior targets.",
                output_profile=_profile_matrix(lag_matrix[start_index:], lag_names),
                generated_features=lag_names,
            )
        except Exception as exc:
            return fail(step, exc)
    else:
        skip("lag_generator", "Lag features are disabled by featureConfig.")

    if normalized_config["rollingFeatures"]:
        step = begin("rolling_generator", "Generate rolling statistics from shifted target history.", source_profile)
        try:
            shifted = pd.Series(normalized_values, dtype=float).shift(1)
            rolling_names = ["rolling_mean_3", "rolling_mean_7", "rolling_std_7"]
            rolling_matrix = np.column_stack(
                [
                    shifted.rolling(3, min_periods=1).mean().to_numpy(dtype=float),
                    shifted.rolling(7, min_periods=1).mean().to_numpy(dtype=float),
                    shifted.rolling(7, min_periods=1).std(ddof=0).fillna(0.0).to_numpy(dtype=float),
                ]
            )
            family_matrices["rolling"] = (rolling_matrix, rolling_names)
            complete(
                step,
                output_summary="Generated rolling means and standard deviation from shifted history.",
                output_profile=_profile_matrix(rolling_matrix[start_index:], rolling_names),
                generated_features=rolling_names,
            )
        except Exception as exc:
            return fail(step, exc)
    else:
        skip("rolling_generator", "Rolling features are disabled by featureConfig.")

    step = begin("feature_merge", "Merge enabled feature families into one chronological matrix.")
    try:
        ordered_families = [family for family in ("lag", "rolling", "calendar", "covariates") if family in family_matrices]
        if not ordered_families:
            raise ValueError("At least one feature family must be enabled for feature-consuming models.")
        merged_names = [name for family in ordered_families for name in family_matrices[family][1]]
        merged_matrix = np.column_stack([family_matrices[family][0] for family in ordered_families])[start_index:]
        merged_targets = normalized_values[start_index:]
        complete(
            step,
            output_summary=f"Merged {len(merged_names)} feature columns after {start_index} warmup rows.",
            output_profile=_profile_matrix(merged_matrix, merged_names),
            generated_features=merged_names,
        )
    except Exception as exc:
        return fail(step, exc)

    step = begin("leakage_guard", "Verify temporal boundaries and finite matrix values.", _profile_matrix(merged_matrix, merged_names))
    try:
        if start_index < 1:
            raise ValueError("Feature warmup must exclude the current target row.")
        if merged_matrix is None or not len(merged_matrix):
            raise ValueError("Feature matrix is empty after warmup.")
        if not np.isfinite(merged_matrix).all():
            raise ValueError("Feature matrix contains NaN or infinite values after warmup.")
        if len(merged_targets) != len(merged_matrix):
            raise ValueError("Feature matrix and target vector are not aligned.")
        complete(
            step,
            output_summary="Leakage guard passed: target-derived features use prior observations only.",
            output_profile=_profile_matrix(merged_matrix, merged_names),
        )
    except Exception as exc:
        return fail(step, exc)

    if consumers:
        step = begin("feature_selection", f"Select deterministic features for {', '.join(consumers)}.")
        selected_matrix = merged_matrix
        selected_names = list(merged_names)
        dropped_names: list[str] = []
        complete(
            step,
            output_summary=f"Selected all {len(selected_names)} valid configured features.",
            output_profile=_profile_matrix(selected_matrix, selected_names),
            selected_features=selected_names,
            dropped_features=dropped_names,
        )
    else:
        selected_matrix = merged_matrix
        selected_names = []
        skip("feature_selection", "No selected model consumes explicit engineered features.")

    if consumers:
        step = begin("matrix_ready", "Freeze the shared training matrix for feature-consuming models.")
        complete(
            step,
            output_summary=f"Shared matrix is ready for {len(consumers)} model(s).",
            output_profile=_profile_matrix(selected_matrix, selected_names),
            selected_features=selected_names,
        )
        prepared = PreparedFeatureMatrix(
            featureValues=np.asarray(selected_matrix, dtype=float),
            targets=np.asarray(merged_targets, dtype=float),
            featureNames=selected_names,
            times=normalized_times,
            values=[float(value) for value in normalized_values],
            frequency=frequency,
            covariates=normalized_covariates,
            featureConfig=normalized_config,
            startIndex=start_index,
        )
    else:
        skip("matrix_ready", "Feature matrix is not required by the selected models.")
        prepared = None

    target.status = "completed"
    target.currentStepId = None
    target.progressPercent = 100
    _apply_final_metadata(target, selected_names, merged_names, consumers)
    emit()
    return FeatureFactoryResult(prepared=prepared, pipeline=target)


def _profile_matrix(values: np.ndarray | None, names: list[str]) -> RuntimeFeatureDataProfile:
    if values is None:
        return RuntimeFeatureDataProfile(columns=list(names), columnCount=len(names))
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    profiles: list[RuntimeFeatureColumnProfile] = []
    missing_count = int(np.isnan(matrix).sum()) if matrix.size else 0
    invalid_count = int(np.isinf(matrix).sum()) if matrix.size else 0
    for index, name in enumerate(names):
        column = matrix[:, index] if matrix.shape[1] > index else np.asarray([], dtype=float)
        finite = column[np.isfinite(column)]
        profiles.append(
            RuntimeFeatureColumnProfile(
                name=name,
                nonNullCount=int(len(finite)),
                nullCount=int(len(column) - len(finite)),
                minimum=float(np.min(finite)) if len(finite) else None,
                maximum=float(np.max(finite)) if len(finite) else None,
                mean=float(np.mean(finite)) if len(finite) else None,
                std=float(np.std(finite, ddof=0)) if len(finite) else None,
            )
        )
    return RuntimeFeatureDataProfile(
        rowCount=int(matrix.shape[0]),
        columnCount=int(matrix.shape[1]),
        columns=list(names),
        missingValueCount=missing_count,
        invalidValueCount=invalid_count,
        memoryBytes=int(matrix.nbytes),
        columnProfiles=profiles,
    )


def _apply_final_metadata(
    target: RuntimeFeaturePipelineTarget,
    selected_names: list[str],
    generated_names: list[str],
    consumers: list[str],
) -> None:
    selected_lookup = set(selected_names)
    name_map = {
        "Lag1": "lag_1",
        "Lag2": "lag_2",
        "Lag3": "lag_3",
        "Lag7": "lag_7",
        "RollingMean3": "rolling_mean_3",
        "RollingMean7": "rolling_mean_7",
        "RollingStd7": "rolling_std_7",
        "TimeIndex": "time_index",
        "Weekday": "day_of_week",
        "Month": "month",
    }
    selection_items: list[RuntimeFeatureSelectionItem] = []
    for node in target.lineage:
        if node.family == "target":
            continue
        canonical_name = name_map.get(node.name, node.name)
        selected = canonical_name in selected_lookup
        node.selected = selected
        node.lifecycle = "used" if selected else "dropped"
        node.modelIds = list(consumers) if selected else []
        node.droppedReason = None if selected else node.droppedReason or "Feature was not selected by the shared factory."
        node.lifecycleTrail = ["Generated", "Selected", "Trained"] if selected else ["Generated", "Dropped"]
        selection_items.append(
            RuntimeFeatureSelectionItem(
                name=canonical_name,
                status="selected" if selected else "dropped",
                reason=None if selected else node.droppedReason,
            )
        )
    target.selection = RuntimeFeatureSelectionSummary(
        generatedCount=len(generated_names),
        selectedCount=len(selected_names),
        droppedCount=max(len(generated_names) - len(selected_names), 0),
        items=selection_items,
    )
    raw_columns = target.summary.rawColumnCount if target.summary else 0
    covariate_count = len(target.covariates)
    target.summary = RuntimeFeatureFactorySummary(
        rawColumnCount=raw_columns,
        generatedFeatureCount=len(generated_names),
        userCovariateCount=covariate_count,
        selectedFeatureCount=len(selected_names),
        droppedFeatureCount=max(len(generated_names) - len(selected_names), 0),
        importantFeatureCount=0,
        shapSupportedFeatureCount=0,
    )
    for family in target.families:
        family_nodes = [node for node in target.lineage if node.family == family.id]
        family.generatedCount = len(family_nodes)
        family.selectedCount = sum(node.selected for node in family_nodes)
        family.importantCount = 0