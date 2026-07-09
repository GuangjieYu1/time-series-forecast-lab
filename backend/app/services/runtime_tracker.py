from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from threading import Lock
from typing import Any

from app.schemas import (
    ModelProgress,
    RuntimeFeaturePipelineTarget,
    RuntimeModelConsole,
    RuntimeOptimizationState,
    RuntimeOptimizationTrial,
    RuntimeRunDetail,
)
from app.services.model_registry import MODEL_CAPABILITIES
from app.services.runtime_events import (
    build_resource_snapshot,
    elapsed_seconds,
    make_log_entry,
    make_runtime_event,
    make_timeline_entry,
    utc_now,
)
from app.services.runtime_state_machine import build_state_machine, stage_label, transition_state_machine


TREE_MODEL_IDS = {"xgboost", "lightgbm", "random_forest"}


class RuntimeTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, RuntimeRunDetail] = {}
        self._experiment_aliases: dict[str, str] = {}
        self._scopes: dict[str, dict[str, str]] = {}

    def start(
        self,
        run_id: str,
        *,
        kind: str,
        model_rows: list[ModelProgress],
        message: str,
        device: str = "cpu",
        estimated_total_seconds: float | None = None,
        estimated_model_seconds: dict[tuple[str, str], float] | None = None,
        compute_targets: dict[str, str] | None = None,
        parameter_strategy: str = "default",
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> RuntimeRunDetail:
        now = utc_now()
        models: list[RuntimeModelConsole] = []
        for row in model_rows:
            model_id = row.modelId
            model_name = row.modelName
            estimated_seconds = (estimated_model_seconds or {}).get((row.targetColumn, model_id))
            compute_target = str((compute_targets or {}).get(model_id) or ("gpu" if MODEL_CAPABILITIES.get(model_id, None) and MODEL_CAPABILITIES[model_id].requiresGpu else "cpu"))
            models.append(
                RuntimeModelConsole(
                    modelId=model_id,
                    modelName=model_name,
                    targetColumn=row.targetColumn,
                    status=row.status,
                    currentStage="pending",
                    progressPercent=row.percent,
                    message=row.message,
                    elapsedSeconds=0.0,
                    estimatedSeconds=estimated_seconds,
                    estimatedRemainingSeconds=estimated_seconds,
                    fitSeconds=row.fitSeconds,
                    predictSeconds=row.predictSeconds,
                    tuningSeconds=None,
                    metricLabel="MAE",
                    currentMetric=None,
                    bestMetric=None,
                    selectedParams={},
                    warnings=[],
                    computeTarget="gpu" if str(compute_target).lower() == "gpu" else "cpu",
                    resource=build_resource_snapshot(device),
                    optimization=self._initial_optimization_state(
                        model_id=model_id,
                        model_name=model_name,
                        target_column=row.targetColumn,
                        parameter_strategy=parameter_strategy,
                    ),
                    error=row.error,
                )
            )
        detail = RuntimeRunDetail(
            runId=run_id,
            kind=kind,
            status="running",
            currentStage="pending",
            currentStageLabel=stage_label("pending"),
            overallPercent=1,
            message=message,
            estimatedTotalSeconds=estimated_total_seconds,
            estimatedRemainingSeconds=estimated_total_seconds,
            elapsedSeconds=0.0,
            startedAt=now,
            updatedAt=now,
            stateMachine=build_state_machine(now),
            resources=build_resource_snapshot(device),
            models=models,
            logs=[make_log_entry(stage="pending", message=message, timestamp=now)],
            timeline=[make_timeline_entry(stage="pending", status="running", message=message, timestamp=now, overall_percent=1)],
            events=[
                make_runtime_event(
                    run_id=run_id,
                    sequence=1,
                    event_type="stage",
                    stage="pending",
                    status="running",
                    message=message,
                    timestamp=now,
                    progress_percent=1,
                )
            ],
            featurePipeline=[],
            optimization=[model.optimization for model in models if model.optimization is not None],
        )
        with self._lock:
            self._cleanup_locked(now)
            self._runs[run_id] = detail
            if user_id and workspace_id:
                self._scopes[run_id] = {"userId": user_id, "workspaceId": workspace_id}
            return detail.model_copy(deep=True)

    def set_overall(
        self,
        run_id: str,
        *,
        stage: str,
        message: str,
        overall_percent: int,
        current_target: str | None = None,
        terminal_status: str = "running",
        level: str = "info",
    ) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            now = utc_now()
            runtime_stage = stage if stage in {"pending", "loading", "cleaning", "feature_engineering", "feature_selection", "auto_tuning", "training", "forecast", "residual_analysis", "finished", "failed"} else "pending"
            detail.currentStage = runtime_stage
            detail.currentStageLabel = stage_label(runtime_stage)
            detail.status = "failed" if terminal_status == "failed" else "completed" if terminal_status == "completed" else "running"
            detail.message = message
            detail.currentTarget = current_target
            detail.overallPercent = overall_percent
            detail.updatedAt = now
            detail.elapsedSeconds = elapsed_seconds(detail.startedAt, now)
            if detail.estimatedTotalSeconds is not None:
                detail.estimatedRemainingSeconds = max(round(detail.estimatedTotalSeconds - detail.elapsedSeconds, 4), 0.0)
            detail.resources = build_resource_snapshot(detail.resources.device if detail.resources else "cpu")
            detail.stateMachine = transition_state_machine(
                detail.stateMachine,
                stage=runtime_stage,
                now=now,
                terminal_status=terminal_status,
            )
            self._append_timeline_locked(
                detail,
                stage=runtime_stage,
                status="failed" if terminal_status == "failed" else "completed" if terminal_status == "completed" and runtime_stage == "finished" else "running",
                message=message,
                overall_percent=overall_percent,
            )
            self._append_log_locked(detail, stage=runtime_stage, level=level, message=message, target_column=current_target)
            return detail.model_copy(deep=True)

    def set_feature_pipeline(self, run_id: str, pipeline_target: RuntimeFeaturePipelineTarget) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            replaced = False
            targets = deepcopy(detail.featurePipeline)
            for index, item in enumerate(targets):
                if item.targetColumn == pipeline_target.targetColumn:
                    targets[index] = pipeline_target
                    replaced = True
                    break
            if not replaced:
                targets.append(pipeline_target)
            detail.featurePipeline = targets
            detail.updatedAt = utc_now()
            summary = pipeline_target.summary
            active_step = next(
                (step for step in pipeline_target.steps if step.id == pipeline_target.currentStepId),
                pipeline_target.steps[-1] if pipeline_target.steps else None,
            )
            action = active_step.status if active_step else pipeline_target.status
            event_status = "failed" if action == "failed" else "running" if action in {"pending", "running"} else "completed"
            message = (
                f"{active_step.label}: {action}"
                if active_step
                else f"Feature pipeline {pipeline_target.status} for {pipeline_target.targetColumn}."
            )
            self._append_event_locked(
                detail,
                event_type="feature",
                stage="feature_engineering",
                status=event_status,
                message=message,
                target_column=pipeline_target.targetColumn,
                progress_percent=pipeline_target.progressPercent,
                payload={
                    "action": action,
                    "step": active_step.model_dump(mode="json") if active_step else None,
                    "pipelineStatus": pipeline_target.status,
                    "pipelineProgressPercent": pipeline_target.progressPercent,
                    "generatedFeatureCount": summary.generatedFeatureCount if summary else len(pipeline_target.lineage),
                    "selectedFeatureCount": summary.selectedFeatureCount if summary else 0,
                    "warningCount": len(pipeline_target.warnings),
                    "traceMode": pipeline_target.traceMode,
                    "featurePipelineVersion": pipeline_target.schemaVersion,
                },
            )
            return detail.model_copy(deep=True)

    def set_estimates(
        self,
        run_id: str,
        *,
        estimated_total_seconds: float | None,
        estimated_model_seconds: dict[tuple[str, str], float] | None = None,
        compute_targets: dict[str, str] | None = None,
    ) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            detail.estimatedTotalSeconds = estimated_total_seconds
            if estimated_total_seconds is not None:
                detail.estimatedRemainingSeconds = max(round(estimated_total_seconds - detail.elapsedSeconds, 4), 0.0)
            models = deepcopy(detail.models)
            for index, model in enumerate(models):
                estimate = (estimated_model_seconds or {}).get((model.targetColumn, model.modelId))
                if estimate is not None:
                    model.estimatedSeconds = estimate
                    model.estimatedRemainingSeconds = max(round(estimate - model.elapsedSeconds, 4), 0.0)
                if compute_targets and model.modelId in compute_targets:
                    model.computeTarget = "gpu" if str(compute_targets[model.modelId]).lower() == "gpu" else "cpu"
                models[index] = model
            detail.models = models
            detail.updatedAt = utc_now()
            return detail.model_copy(deep=True)

    def update_model(
        self,
        run_id: str,
        *,
        target_column: str,
        model_id: str,
        status: str,
        message: str,
        progress_percent: int,
        current_stage: str,
        fit_seconds: float | None = None,
        predict_seconds: float | None = None,
        tuning_seconds: float | None = None,
        error: str | None = None,
        level: str = "info",
        metric_label: str | None = None,
        metric_value: float | None = None,
        params: dict[str, Any] | None = None,
        best_metric: float | None = None,
        warnings: list[str] | None = None,
    ) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            now = utc_now()
            models = deepcopy(detail.models)
            for index, model in enumerate(models):
                if model.targetColumn == target_column and model.modelId == model_id:
                    model.status = status
                    model.currentStage = current_stage
                    model.progressPercent = progress_percent
                    model.message = message
                    model.fitSeconds = fit_seconds if fit_seconds is not None else model.fitSeconds
                    model.predictSeconds = predict_seconds if predict_seconds is not None else model.predictSeconds
                    model.tuningSeconds = tuning_seconds if tuning_seconds is not None else model.tuningSeconds
                    model.metricLabel = metric_label if metric_label is not None else model.metricLabel
                    model.currentMetric = metric_value if metric_value is not None else model.currentMetric
                    model.bestMetric = best_metric if best_metric is not None else model.bestMetric
                    model.selectedParams = dict(params or model.selectedParams)
                    model.warnings = list(warnings or model.warnings)
                    model.error = error
                    model.resource = build_resource_snapshot(detail.resources.device if detail.resources else "cpu")
                    model.elapsedSeconds = round(
                        float(model.fitSeconds or 0.0) + float(model.predictSeconds or 0.0) + float(model.tuningSeconds or 0.0),
                        4,
                    )
                    if model.estimatedSeconds is not None:
                        model.estimatedRemainingSeconds = max(round(model.estimatedSeconds - model.elapsedSeconds, 4), 0.0)
                    models[index] = model
                    self._append_timeline_locked(
                        detail,
                        stage=current_stage,
                        status="failed" if status == "failed" else "completed" if status == "success" else "running",
                        message=message,
                        model_id=model_id,
                        model_name=model.modelName,
                        target_column=target_column,
                        overall_percent=detail.overallPercent,
                    )
                    self._append_log_locked(
                        detail,
                        stage=current_stage,
                        level="error" if status == "failed" else level,
                        message=message,
                        model_id=model_id,
                        model_name=model.modelName,
                        target_column=target_column,
                        metric_label=metric_label,
                        metric_value=metric_value,
                        params=params,
                    )
                    break
            detail.models = models
            detail.updatedAt = now
            detail.elapsedSeconds = elapsed_seconds(detail.startedAt, now)
            detail.optimization = [model.optimization for model in detail.models if model.optimization is not None]
            if detail.estimatedTotalSeconds is not None:
                detail.estimatedRemainingSeconds = max(round(detail.estimatedTotalSeconds - detail.elapsedSeconds, 4), 0.0)
            return detail.model_copy(deep=True)

    def update_optimization(
        self,
        run_id: str,
        *,
        target_column: str,
        model_id: str,
        current_trial: int,
        total_trials: int,
        message: str,
        params: dict[str, Any] | None = None,
        current_metric: float | None = None,
        best_metric: float | None = None,
        tuning_seconds: float | None = None,
        trial_status: str = "running",
        strategy_label: str | None = None,
        sampler: str | None = None,
        pruner: str | None = None,
    ) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            models = deepcopy(detail.models)
            for index, model in enumerate(models):
                if model.targetColumn != target_column or model.modelId != model_id:
                    continue
                optimization = model.optimization or self._initial_optimization_state(
                    model_id=model.modelId,
                    model_name=model.modelName,
                    target_column=target_column,
                    parameter_strategy="auto",
                )
                optimization.enabled = True
                optimization.status = "running" if trial_status in {"running", "pruned"} else "completed" if trial_status == "success" else "failed"
                optimization.strategyLabel = strategy_label or optimization.strategyLabel
                optimization.sampler = sampler if sampler is not None else optimization.sampler
                optimization.pruner = pruner if pruner is not None else optimization.pruner
                optimization.currentTrial = current_trial
                optimization.totalTrials = max(total_trials, current_trial)
                optimization.lastMessage = message
                optimization.currentMetric = current_metric
                optimization.bestMetric = best_metric if best_metric is not None else optimization.bestMetric
                if params:
                    optimization.selectedParams = params if trial_status == "success" else optimization.selectedParams
                if current_trial:
                    trials = deepcopy(optimization.trials)
                    existing_index = next((trial_index for trial_index, trial in enumerate(trials) if trial.trialNumber == current_trial), None)
                    next_trial = RuntimeOptimizationTrial(
                        trialNumber=current_trial,
                        params=params or {},
                        status=trial_status,
                        metric=current_metric,
                        metricLabel=optimization.metricLabel,
                        elapsedSeconds=float(tuning_seconds or 0.0),
                        selected=trial_status == "success" and best_metric is not None and current_metric == best_metric,
                        message=message,
                    )
                    if existing_index is None:
                        trials.append(next_trial)
                    else:
                        trials[existing_index] = next_trial
                    optimization.trials = trials
                model.optimization = optimization
                model.tuningSeconds = tuning_seconds if tuning_seconds is not None else model.tuningSeconds
                model.currentStage = "auto_tuning"
                model.metricLabel = optimization.metricLabel
                model.currentMetric = current_metric
                model.bestMetric = best_metric if best_metric is not None else model.bestMetric
                model.selectedParams = dict(optimization.selectedParams or {})
                models[index] = model
                optimization_level = "warn" if trial_status in {"failed", "pruned"} else "success" if trial_status == "success" else "info"
                self._append_log_locked(
                    detail,
                    stage="auto_tuning",
                    level=optimization_level,
                    message=message,
                    model_id=model_id,
                    model_name=model.modelName,
                    target_column=target_column,
                    metric_label="MAE",
                    metric_value=current_metric,
                    params=params,
                )
                self._append_timeline_locked(
                    detail,
                    stage="auto_tuning",
                    status="running",
                    level=optimization_level,
                    message=message,
                    model_id=model_id,
                    model_name=model.modelName,
                    target_column=target_column,
                    overall_percent=detail.overallPercent,
                )
                break
            detail.models = models
            detail.optimization = [model.optimization for model in detail.models if model.optimization is not None]
            detail.updatedAt = utc_now()
            return detail.model_copy(deep=True)

    def finalize(
        self,
        run_id: str,
        *,
        status: str,
        message: str,
        error: str | None = None,
        experiment_id: str | None = None,
    ) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            now = utc_now()
            detail.status = status
            detail.currentStage = "finished" if status == "completed" else "failed"
            detail.currentStageLabel = stage_label(detail.currentStage)
            detail.message = message
            detail.updatedAt = now
            detail.error = error
            detail.overallPercent = 100
            detail.elapsedSeconds = elapsed_seconds(detail.startedAt, now)
            detail.estimatedRemainingSeconds = 0.0 if status == "completed" else detail.estimatedRemainingSeconds
            detail.stateMachine = transition_state_machine(
                detail.stateMachine,
                stage=detail.currentStage,
                now=now,
                terminal_status=status,
            )
            if experiment_id:
                detail.experimentId = experiment_id
                self._experiment_aliases[experiment_id] = run_id
                if run_id in self._scopes:
                    self._scopes[experiment_id] = dict(self._scopes[run_id])
            self._append_timeline_locked(
                detail,
                stage=detail.currentStage,
                status="completed" if status == "completed" else "failed",
                message=message,
                overall_percent=100,
            )
            self._append_log_locked(
                detail,
                stage=detail.currentStage,
                level="success" if status == "completed" else "error",
                message=message if not error else f"{message} {error}",
            )
            return detail.model_copy(deep=True)

    def attach_experiment_id(self, run_id: str, experiment_id: str) -> RuntimeRunDetail | None:
        with self._lock:
            detail = self._runs.get(run_id)
            if detail is None:
                return None
            detail.experimentId = experiment_id
            self._experiment_aliases[experiment_id] = run_id
            if run_id in self._scopes:
                self._scopes[experiment_id] = dict(self._scopes[run_id])
            return detail.model_copy(deep=True)

    def get(self, runtime_id: str) -> RuntimeRunDetail | None:
        with self._lock:
            run_id = self._resolve_runtime_id_locked(runtime_id)
            detail = self._runs.get(run_id)
            return detail.model_copy(deep=True) if detail else None

    def get_scope(self, runtime_id: str) -> dict[str, str] | None:
        with self._lock:
            run_id = self._resolve_runtime_id_locked(runtime_id)
            scope = self._scopes.get(runtime_id) or self._scopes.get(run_id)
            return dict(scope) if scope else None

    def resolve_runtime_id(self, runtime_id: str) -> str:
        with self._lock:
            return self._resolve_runtime_id_locked(runtime_id)

    def get_logs(self, runtime_id: str):
        detail = self.get(runtime_id)
        return detail.logs if detail else []

    def get_feature_pipeline(self, runtime_id: str):
        detail = self.get(runtime_id)
        return detail.featurePipeline if detail else []

    def get_optimization(self, runtime_id: str):
        detail = self.get(runtime_id)
        return detail.optimization if detail else []

    def get_timeline(self, runtime_id: str):
        detail = self.get(runtime_id)
        return detail.timeline if detail else []

    def _append_event_locked(
        self,
        detail: RuntimeRunDetail,
        *,
        event_type: str,
        stage: str,
        status: str,
        message: str,
        model_id: str | None = None,
        target_column: str | None = None,
        progress_percent: int | None = None,
        metric_label: str | None = None,
        metric_value: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        detail.events.append(
            make_runtime_event(
                run_id=detail.runId,
                sequence=len(detail.events) + 1,
                event_type=event_type,
                stage=stage,
                status=status,
                message=message,
                model_id=model_id,
                target_column=target_column,
                progress_percent=progress_percent,
                metric_label=metric_label,
                metric_value=metric_value,
                payload=payload,
            )
        )
    def _append_log_locked(
        self,
        detail: RuntimeRunDetail,
        *,
        stage: str,
        level: str,
        message: str,
        model_id: str | None = None,
        model_name: str | None = None,
        target_column: str | None = None,
        metric_label: str | None = None,
        metric_value: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        if detail.logs:
            last = detail.logs[-1]
            if (
                last.stage == stage
                and last.message == message
                and last.modelId == model_id
                and last.targetColumn == target_column
            ):
                return
        detail.logs.append(
            make_log_entry(
                stage=stage,
                level=level,
                message=message,
                model_id=model_id,
                model_name=model_name,
                target_column=target_column,
                metric_label=metric_label,
                metric_value=metric_value,
                params=params,
            )
        )
        event_type = "optimization" if stage == "auto_tuning" else "model" if model_id else "terminal" if stage in {"finished", "failed"} else "log"
        event_status = "failed" if level == "error" else "completed" if stage == "finished" else "running"
        self._append_event_locked(
            detail,
            event_type=event_type,
            stage=stage,
            status=event_status,
            message=message,
            model_id=model_id,
            target_column=target_column,
            progress_percent=detail.overallPercent,
            metric_label=metric_label,
            metric_value=metric_value,
            payload=params,
        )

    def _append_timeline_locked(
        self,
        detail: RuntimeRunDetail,
        *,
        stage: str,
        status: str,
        level: str = "info",
        message: str | None = None,
        model_id: str | None = None,
        model_name: str | None = None,
        target_column: str | None = None,
        overall_percent: int | None = None,
    ) -> None:
        if detail.timeline:
            last = detail.timeline[-1]
            if (
                last.stage == stage
                and last.status == status
                and last.modelId == model_id
                and last.targetColumn == target_column
                and last.message == message
            ):
                return
        detail.timeline.append(
            make_timeline_entry(
                stage=stage,
                status=status,
                level=level,
                message=message,
                model_id=model_id,
                model_name=model_name,
                target_column=target_column,
                overall_percent=overall_percent,
            )
        )

    def _initial_optimization_state(
        self,
        *,
        model_id: str,
        model_name: str,
        target_column: str,
        parameter_strategy: str,
    ) -> RuntimeOptimizationState:
        if parameter_strategy != "auto":
            return RuntimeOptimizationState(
                modelId=model_id,
                modelName=model_name,
                targetColumn=target_column,
                enabled=False,
                strategyLabel="Default Parameters",
                status="idle",
            )
        if model_id in TREE_MODEL_IDS:
            return RuntimeOptimizationState(
                modelId=model_id,
                modelName=model_name,
                targetColumn=target_column,
                enabled=True,
                strategyLabel="Optuna Optimization Engine",
                sampler="TPE",
                pruner="Successive Halving",
                status="idle",
            )
        if model_id == "timesfm":
            return RuntimeOptimizationState(
                modelId=model_id,
                modelName=model_name,
                targetColumn=target_column,
                enabled=True,
                strategyLabel="Foundation Model Context Search",
                sampler="Context / Normalize Sweep",
                pruner="Budget Stopper",
                status="idle",
            )
        return RuntimeOptimizationState(
            modelId=model_id,
            modelName=model_name,
            targetColumn=target_column,
            enabled=True,
            strategyLabel="Model-native Optimizer",
            sampler="Built-in",
            pruner=None,
            status="idle",
        )

    def _resolve_runtime_id_locked(self, runtime_id: str) -> str:
        return self._experiment_aliases.get(runtime_id, runtime_id)

    def _cleanup_locked(self, now) -> None:
        cutoff = now - timedelta(hours=2)
        expired = [
            run_id
            for run_id, detail in self._runs.items()
            if detail.updatedAt < cutoff and detail.status in {"completed", "failed"}
        ]
        for run_id in expired:
            experiment_aliases = [experiment_id for experiment_id, alias_run_id in self._experiment_aliases.items() if alias_run_id == run_id]
            for experiment_id in experiment_aliases:
                self._experiment_aliases.pop(experiment_id, None)
                self._scopes.pop(experiment_id, None)
            self._runs.pop(run_id, None)
            self._scopes.pop(run_id, None)


runtime_tracker = RuntimeTracker()
