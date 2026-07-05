from __future__ import annotations

import json
from typing import Any

from app.db.models import ExperimentRecord
from app.schemas import (
    RuntimeCovariateDescriptor,
    RuntimeFeatureFamily,
    RuntimeFeatureFactorySummary,
    RuntimeFeatureMachine,
    RuntimeFeatureNode,
    RuntimeFeaturePipelineStep,
    RuntimeFeaturePipelineTarget,
    RuntimeFeatureSelectionItem,
    RuntimeFeatureSelectionSummary,
    RuntimeLogEntry,
    RuntimeModelConsole,
    RuntimeOptimizationState,
    RuntimeOptimizationTrial,
    RuntimeResourceSnapshot,
    RuntimeRunDetail,
)
from app.services.covariate_flow import describe_covariates
from app.services.model_registry import MODEL_CAPABILITIES
from app.services.holiday_features import HOLIDAY_FEATURE_NAMES
from app.services.runtime_events import make_log_entry, make_runtime_event
from app.services.runtime_state_machine import build_state_machine, stage_label, transition_state_machine


TREE_MODEL_IDS = {"xgboost", "lightgbm", "random_forest"}
ML_FEATURE_MODEL_IDS = {
    model_id for model_id, capability in MODEL_CAPABILITIES.items() if capability.supportsCovariates
}


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _with_runtime_events(detail: RuntimeRunDetail) -> RuntimeRunDetail:
    if detail.events:
        return detail
    for log in detail.logs:
        status = "failed" if log.level == "error" else "completed" if log.stage == "finished" else "running"
        event_type = "optimization" if log.stage == "auto_tuning" else "model" if log.modelId else "terminal" if log.stage in {"finished", "failed"} else "log"
        detail.events.append(
            make_runtime_event(
                run_id=detail.runId,
                sequence=len(detail.events) + 1,
                event_type=event_type,
                stage=log.stage,
                status=status,
                message=log.message,
                timestamp=log.timestamp,
                model_id=log.modelId,
                target_column=log.targetColumn,
                progress_percent=100 if status == "completed" else None,
                metric_label=log.metricLabel,
                metric_value=log.metricValue,
                payload=log.params,
            )
        )
    if not detail.events:
        for item in detail.timeline:
            detail.events.append(
                make_runtime_event(
                    run_id=detail.runId,
                    sequence=len(detail.events) + 1,
                    event_type="model" if item.modelId else "stage",
                    stage=item.stage,
                    status=item.status,
                    message=item.message or item.label,
                    timestamp=item.timestamp,
                    model_id=item.modelId,
                    target_column=item.targetColumn,
                    progress_percent=item.overallPercent,
                )
            )
    return detail

def load_runtime_from_record(record: ExperimentRecord) -> RuntimeRunDetail | None:
    if record.runtime_json:
        try:
            return _with_runtime_events(RuntimeRunDetail.model_validate(_loads(record.runtime_json, {})))
        except Exception:
            pass

    try:
        config = _loads(record.config_json, {})
        data_profile = _loads(record.data_profile_json, {})
        model_logs = _loads(record.model_logs_json, [])
        manifest = _loads(record.manifest_json, {})
    except Exception:
        return None

    targets = data_profile.get("targets") or []
    selected_models = [str(item) for item in config.get("selectedModels", []) if item]
    started_at = record.created_at
    models: list[RuntimeModelConsole] = []
    optimization: list[RuntimeOptimizationState] = []
    logs: list[RuntimeLogEntry] = []
    total_seconds = 0.0

    model_name_by_id = {model_id: capability.name for model_id, capability in MODEL_CAPABILITIES.items()}
    optimization_by_key: dict[tuple[str, str], RuntimeOptimizationState] = {}

    for row in model_logs:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("modelId") or "")
        target_column = str(row.get("targetColumn") or record.target_column)
        runtime = row.get("runtime") or {}
        tuning = row.get("tuning") or {}
        fit_seconds = float(runtime.get("fitSeconds") or 0.0)
        predict_seconds = float(runtime.get("predictSeconds") or 0.0)
        tuning_seconds = float(tuning.get("tuningSeconds") or 0.0)
        elapsed = round(fit_seconds + predict_seconds + tuning_seconds, 4)
        total_seconds += max(elapsed, 0.0)
        capability = MODEL_CAPABILITIES.get(model_id)
        model_name = str(row.get("modelName") or model_name_by_id.get(model_id) or model_id)
        compute_target = "gpu" if capability and capability.requiresGpu else "cpu"
        console = RuntimeModelConsole(
            modelId=model_id,
            modelName=model_name,
            targetColumn=target_column,
            status=row.get("status") or "success",
            currentStage="finished" if row.get("status") == "success" else "failed",
            progressPercent=100,
            message="模型运行成功。" if row.get("status") == "success" else (row.get("error") or "模型运行失败。"),
            elapsedSeconds=elapsed,
            estimatedSeconds=elapsed,
            estimatedRemainingSeconds=0.0 if row.get("status") == "success" else None,
            fitSeconds=fit_seconds or None,
            predictSeconds=predict_seconds or None,
            tuningSeconds=tuning_seconds or None,
            computeTarget=compute_target,
            resource=_resource_from_manifest(manifest, compute_target),
            optimization=build_optimization_state_from_log(
                model_id=model_id,
                model_name=model_name,
                target_column=target_column,
                tuning=tuning,
                parameter_strategy=str(config.get("parameterStrategy") or "default"),
            ),
            error=row.get("error"),
        )
        models.append(console)
        optimization_by_key[(target_column, model_id)] = console.optimization or build_optimization_state_from_log(
            model_id=model_id,
            model_name=model_name,
            target_column=target_column,
            tuning=tuning,
            parameter_strategy=str(config.get("parameterStrategy") or "default"),
        )
        logs.append(
            make_log_entry(
                stage="finished" if row.get("status") == "success" else "failed",
                level="success" if row.get("status") == "success" else "error",
                message=f"{model_name} / {target_column}：{'完成' if row.get('status') == 'success' else '失败'}。",
                timestamp=record.created_at,
                model_id=model_id,
                model_name=model_name,
                target_column=target_column,
                metric_label="MAE",
                metric_value=_metric_value(row.get("metrics"), "mae"),
            )
        )

    optimization = list(optimization_by_key.values())
    raw_column_count = 0
    if isinstance(manifest, dict):
        raw_column_count = len((((manifest.get("data") or {}) if isinstance(manifest.get("data"), dict) else {}).get("columns") or []))
    feature_pipeline = [
        build_feature_pipeline_target(
            target_profile=target_profile,
            selected_model_ids=selected_models,
            warnings=_target_warnings(target_profile),
            raw_column_count=raw_column_count,
        )
        for target_profile in targets
        if isinstance(target_profile, dict)
    ]

    state_machine = transition_state_machine(
        build_state_machine(started_at),
        stage="finished",
        now=record.created_at,
        terminal_status="completed",
    )

    return _with_runtime_events(RuntimeRunDetail(
        runId=record.id,
        experimentId=record.id,
        kind="backtest",
        status="completed",
        currentStage="finished",
        currentStageLabel=stage_label("finished"),
        overallPercent=100,
        message="实验完成，已从历史记录恢复 runtime 视图。",
        currentTarget=record.target_column,
        estimatedTotalSeconds=round(total_seconds, 4) if total_seconds else None,
        estimatedRemainingSeconds=0.0,
        elapsedSeconds=round(total_seconds, 4),
        startedAt=started_at,
        updatedAt=record.created_at,
        stateMachine=state_machine,
        resources=_resource_from_manifest(manifest, str((manifest.get("environment") or {}).get("device") or "cpu")),
        models=models,
        logs=logs,
        timeline=[],
        featurePipeline=feature_pipeline,
        optimization=optimization,
        error=None,
    ))


def build_feature_pipeline_target(
    *,
    target_profile: dict[str, Any],
    selected_model_ids: list[str],
    warnings: list[str] | None = None,
    raw_column_count: int = 0,
) -> RuntimeFeaturePipelineTarget:
    target_column = str(target_profile.get("targetColumn") or "unknown")
    feature_config = target_profile.get("featureConfig") or {}
    covariate_columns = [str(item) for item in target_profile.get("covariateColumns") or [] if item]
    covariate_descriptors = [
        RuntimeCovariateDescriptor.model_validate(item)
        for item in target_profile.get("covariates") or describe_covariates(covariate_columns)
    ]
    history = target_profile.get("history") or []
    uses_feature_models = any(model_id in ML_FEATURE_MODEL_IDS for model_id in selected_model_ids)
    shap_supported = any(model_id in TREE_MODEL_IDS for model_id in selected_model_ids) and uses_feature_models
    lineage = _build_feature_lineage(
        target_column=target_column,
        covariates=covariate_descriptors,
        feature_config=feature_config,
        selected_model_ids=selected_model_ids,
        uses_feature_models=uses_feature_models,
        history_point_count=len(history),
    )
    families = _summarize_feature_families(lineage, feature_config)
    summary = _build_feature_summary(
        raw_column_count=raw_column_count or int(target_profile.get("rawColumnCount") or 0),
        lineage=lineage,
        covariates=covariate_descriptors,
        shap_supported=shap_supported,
    )
    selection = _build_feature_selection(lineage)
    machines = _build_feature_machines(
        target_column=target_column,
        feature_config=feature_config,
        lineage=lineage,
        covariates=covariate_descriptors,
    )
    steps = [
        RuntimeFeaturePipelineStep(
            id="loading",
            label="Raw Data",
            status="completed",
            inputSummary=f"目标列 `{target_column}` 原始时间序列。",
            outputSummary=f"载入 {len(history)} 个时间点。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="loading",
            label="Data Profiling",
            status="completed",
            inputSummary=f"扫描原始列与协变量配置，共 {summary.rawColumnCount or max(len(covariate_columns) + 2, 2)} 列。",
            outputSummary=f"识别到 {summary.userCovariateCount} 个用户协变量，频率 `{target_profile.get('sourceFrequency') or target_profile.get('detectedFrequency') or 'auto'}`。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="cleaning",
            label="Data Cleaning",
            status="completed",
            inputSummary=f"识别频率 `{target_profile.get('sourceFrequency') or target_profile.get('detectedFrequency') or 'auto'}`。",
            outputSummary=f"清洗后保留 {len(history)} 个有效点。",
            elapsedSeconds=0.0,
            warnings=list(warnings or []),
        ),
        RuntimeFeaturePipelineStep(
            id="feature_engineering",
            label="Feature Factory",
            status="completed",
            inputSummary=f"featureConfig：{json.dumps(feature_config, ensure_ascii=False, sort_keys=True)}",
            outputSummary=f"生成 {summary.generatedFeatureCount} 个派生特征，并接入 {summary.userCovariateCount} 个协变量。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="feature_selection",
            label="Feature Selection",
            status="completed",
            inputSummary="根据 featureConfig 和模型能力筛选可用特征族。",
            outputSummary=f"最终保留 {summary.selectedFeatureCount} 个特征，淘汰 {summary.droppedFeatureCount} 个。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="training",
            label="Model Training",
            status="completed",
            inputSummary="将已选特征输入支持特征工程的模型。",
            outputSummary="模型训练阶段完成。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="residual_analysis",
            label="Feature Importance",
            status="completed",
            inputSummary="汇总模型可解释性支持情况。",
            outputSummary=shap_supported and summary.selectedFeatureCount
            and f"当前树模型链路支持最多 {summary.shapSupportedFeatureCount} 个特征进入 SHAP/importance 解释。"
            or "当前实验未产出可持久化的特征重要性分数。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
        RuntimeFeaturePipelineStep(
            id="finished",
            label="SHAP",
            status="completed",
            inputSummary="检查是否存在可解释特征与支持 SHAP 的模型。",
            outputSummary=shap_supported and "SHAP 支持已准备，可在后续版本接入真实解释值。" or "当前仅记录 SHAP 支持范围，尚未持久化真实 SHAP 数值。",
            elapsedSeconds=0.0,
            warnings=[],
        ),
    ]
    for step in steps:
        step.progressPercent = 100

    return RuntimeFeaturePipelineTarget(
        targetColumn=target_column,
        status="completed",
        progressPercent=100,
        traceMode="legacy_inferred",
        detectedFrequency=target_profile.get("detectedFrequency"),
        warnings=list(warnings or []),
        families=families,
        steps=steps,
        lineage=lineage,
        summary=summary,
        machines=machines,
        covariates=covariate_descriptors,
        selection=selection,
    )


def build_optimization_state_from_log(
    *,
    model_id: str,
    model_name: str,
    target_column: str,
    tuning: dict[str, Any] | None,
    parameter_strategy: str,
) -> RuntimeOptimizationState:
    tuning = tuning if isinstance(tuning, dict) else {}
    enabled = bool(tuning.get("enabled")) or parameter_strategy == "auto"
    strategy_label = str(tuning.get("strategyLabel") or "")
    sampler = tuning.get("sampler")
    pruner = tuning.get("pruner")
    if not strategy_label:
        if parameter_strategy != "auto":
            strategy_label = "Default Parameters"
            sampler = None
            pruner = None
        elif model_id in TREE_MODEL_IDS:
            strategy_label = "Optuna Optimization Engine"
            sampler = sampler or "TPE"
            pruner = pruner or "Successive Halving"
        elif model_id == "timesfm":
            strategy_label = "Foundation Model Context Search"
            sampler = sampler or "Context / Normalize Sweep"
            pruner = pruner or "Budget Stopper"
        else:
            strategy_label = "Model-native Optimizer"
            sampler = sampler or "Built-in"
            pruner = pruner or None

    raw_trials = tuning.get("trials") or []
    trials: list[RuntimeOptimizationTrial] = []
    for item in raw_trials:
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics") or {}
        raw_status = str(item.get("status") or "success")
        trial_status = raw_status if raw_status in {"running", "success", "failed", "pruned"} else "success"
        trials.append(
            RuntimeOptimizationTrial(
                trialNumber=int(item.get("round") or len(trials) + 1),
                params=item.get("params") or {},
                status=trial_status,
                metric=_metric_value(metrics, "mae"),
                metricLabel="MAE",
                elapsedSeconds=float(item.get("elapsedSeconds") or 0.0),
                selected=bool(item.get("selected")),
                message=item.get("message"),
            )
        )

    status = "completed"
    if tuning.get("strategy") == "auto" and not raw_trials:
        status = "running"
    if trials and any(trial.status == "failed" for trial in trials) and not any(trial.selected for trial in trials):
        status = "failed"

    return RuntimeOptimizationState(
        modelId=model_id,
        modelName=model_name,
        targetColumn=target_column,
        enabled=enabled,
        strategyLabel=strategy_label,
        sampler=sampler,
        pruner=pruner,
        currentTrial=int(tuning.get("candidateCount") or len(trials)),
        totalTrials=int(tuning.get("candidateLimit") or len(trials) or 1),
        bestMetric=_safe_float(tuning.get("bestMetric")),
        currentMetric=trials[-1].metric if trials else None,
        metricLabel="MAE",
        selectedParams=tuning.get("selectedParams") or {},
        status=status if enabled else "idle",
        lastMessage=(trials[-1].message if trials else None),
        trials=trials,
        warnings=[str(item) for item in tuning.get("warnings") or [] if item],
    )


def _build_feature_lineage(
    *,
    target_column: str,
    covariates: list[RuntimeCovariateDescriptor],
    feature_config: dict[str, Any],
    selected_model_ids: list[str],
    uses_feature_models: bool,
    history_point_count: int,
) -> list[RuntimeFeatureNode]:
    nodes: list[RuntimeFeatureNode] = [
        RuntimeFeatureNode(
            id=f"{target_column}:raw",
            name=target_column,
            source=target_column,
            formula=target_column,
            family="target",
            lifecycle="used",
            selected=True,
            important=False,
            modelIds=selected_model_ids,
            featureType="generated",
            generator="Raw Dataset",
            machineId="raw_dataset",
            machineLabel="Raw Dataset",
            forecastStrategy="generated",
            backtestStrategy="generated",
            usedDuring=["training", "backtest", "forecast"],
            lifecycleTrail=["Generated", "Used", "Trained"],
        )
    ]
    active_models = selected_model_ids if uses_feature_models else []
    selected = uses_feature_models

    def append_node(
        node_id: str,
        name: str,
        formula: str,
        family: str,
        *,
        source: str | None = None,
        feature_type: RuntimeFeatureNode["featureType"] = "generated",
        generator: str,
        machine_id: str,
        machine_label: str,
        forecast_strategy: RuntimeFeatureNode["forecastStrategy"] = "generated",
        backtest_strategy: RuntimeFeatureNode["backtestStrategy"] = "generated",
        used_during: list[str] | None = None,
        dropped_reason: str | None = None,
    ):
        enabled = family == "covariates" or bool(
            feature_config.get(
                {
                    "lag": "lagFeatures",
                    "rolling": "rollingFeatures",
                    "calendar": "calendarFeatures",
                    "holiday": "holidayFeatures",
                }.get(family, ""),
                False,
            )
        )
        lifecycle: RuntimeFeatureNode["lifecycle"]
        if family == "covariates":
            family_enabled = bool(feature_config.get("covariates", True))
            enabled = family_enabled
        if enabled and selected:
            lifecycle = "used"
        else:
            lifecycle = "dropped"
        nodes.append(
            RuntimeFeatureNode(
                id=node_id,
                name=name,
                source=source or target_column,
                formula=formula,
                family=family,
                lifecycle=lifecycle,
                selected=enabled and selected,
                important=False,
                modelIds=active_models,
                featureType=feature_type,
                generator=generator,
                machineId=machine_id,
                machineLabel=machine_label,
                forecastStrategy=forecast_strategy,
                backtestStrategy=backtest_strategy,
                usedDuring=used_during or ["training", "backtest", "forecast"],
                droppedReason=dropped_reason
                or (
                    None
                    if enabled and selected
                    else "featureConfig 中已关闭该特征族。"
                    if not enabled
                    else "当前模型组合不消费显式特征工程结果。"
                ),
                lifecycleTrail=["Generated", "Selected", "Trained"] if enabled and selected else ["Generated", "Dropped"],
            )
        )

    if feature_config.get("lagFeatures", True):
        for offset in [1, 2, 3, 7]:
            append_node(
                f"{target_column}:lag:{offset}",
                f"Lag{offset}",
                f"{target_column}(t-{offset})",
                "lag",
                generator="Lag Generator",
                machine_id="lag_generator",
                machine_label="Lag Generator",
            )
    if feature_config.get("rollingFeatures", True):
        append_node(
            f"{target_column}:rolling:mean3",
            "RollingMean3",
            f"mean({target_column}[t-2:t])",
            "rolling",
            generator="Rolling Generator",
            machine_id="rolling_generator",
            machine_label="Rolling Generator",
        )
        append_node(
            f"{target_column}:rolling:mean7",
            "RollingMean7",
            f"mean({target_column}[t-6:t])",
            "rolling",
            generator="Rolling Generator",
            machine_id="rolling_generator",
            machine_label="Rolling Generator",
        )
        append_node(
            f"{target_column}:rolling:std7",
            "RollingStd7",
            f"std({target_column}[t-6:t])",
            "rolling",
            generator="Rolling Generator",
            machine_id="rolling_generator",
            machine_label="Rolling Generator",
        )
    if feature_config.get("calendarFeatures", True):
        append_node(
            f"{target_column}:calendar:index",
            "TimeIndex",
            "running_index(t)",
            "calendar",
            source="Date",
            generator="Calendar Generator",
            machine_id="calendar_generator",
            machine_label="Calendar Generator",
        )
        append_node(
            f"{target_column}:calendar:weekday",
            "Weekday",
            "weekday(date)",
            "calendar",
            source="Date",
            generator="Calendar Generator",
            machine_id="calendar_generator",
            machine_label="Calendar Generator",
        )
        append_node(
            f"{target_column}:calendar:month",
            "Month",
            "month(date)",
            "calendar",
            source="Date",
            generator="Calendar Generator",
            machine_id="calendar_generator",
            machine_label="Calendar Generator",
        )
    if feature_config.get("holidayFeatures", True):
        for name in HOLIDAY_FEATURE_NAMES:
            append_node(
                f"{target_column}:holiday:{name}",
                name,
                f"holiday_calendar({name})",
                "holiday",
                source="Holiday Calendar",
                generator="Holiday Generator",
                machine_id="holiday_generator",
                machine_label="Holiday Generator",
            )
    if feature_config.get("covariates", True):
        for descriptor in covariates:
            append_node(
                f"{target_column}:covariate:{descriptor.name}",
                descriptor.name,
                f"{descriptor.name}(t)",
                "covariates",
                source=descriptor.name,
                feature_type=("known_future_covariate" if descriptor.type == "known_future" else "unknown_future_covariate" if descriptor.type == "unknown_future" else "static_covariate"),
                generator=descriptor.generator,
                machine_id="covariate_loader",
                machine_label="Covariate Loader",
                forecast_strategy=descriptor.forecastStrategy,
                backtest_strategy=descriptor.backtestStrategy,
                used_during=descriptor.usedDuring,
                dropped_reason=descriptor.note if not selected else None,
            )
            if descriptor.forecastStrategy == "drop_for_leakage":
                nodes[-1].lifecycle = "dropped"
                nodes[-1].selected = False
                nodes[-1].modelIds = []
                nodes[-1].droppedReason = descriptor.note or "未来值不可用，已在模型训练前丢弃以避免数据泄漏。"
                nodes[-1].lifecycleTrail = ["Generated", "Dropped", "Leakage Guard"]
    if uses_feature_models and history_point_count < 30:
        for node in nodes:
            if node.family in {"lag", "rolling", "calendar", "covariates"} and node.lifecycle == "used":
                node.lifecycleTrail = ["Generated", "Selected", "Trained", "Important"]
    return nodes


def _summarize_feature_families(lineage: list[RuntimeFeatureNode], feature_config: dict[str, Any]) -> list[RuntimeFeatureFamily]:
    families: list[RuntimeFeatureFamily] = []
    for family_id, label in [
        ("target", "Target"),
        ("lag", "Lag"),
        ("rolling", "Rolling"),
        ("calendar", "日历特征"),
        ("holiday", "节假日特征"),
        ("covariates", "协变量"),
    ]:
        family_nodes = [node for node in lineage if node.family == family_id]
        enabled = True if family_id == "target" else bool(
            feature_config.get(
                {
                    "lag": "lagFeatures",
                    "rolling": "rollingFeatures",
                    "calendar": "calendarFeatures",
                    "holiday": "holidayFeatures",
                    "covariates": "covariates",
                }.get(family_id, ""),
                False,
            )
        )
        if not family_nodes and not enabled:
            continue
        families.append(
            RuntimeFeatureFamily(
                id=family_id,
                label=label,
                enabled=enabled,
                generatedCount=len(family_nodes),
                selectedCount=sum(1 for node in family_nodes if node.selected or node.lifecycle in {"selected", "used", "important"}),
                importantCount=sum(1 for node in family_nodes if node.important),
            )
        )
    return families


def _build_feature_summary(
    *,
    raw_column_count: int,
    lineage: list[RuntimeFeatureNode],
    covariates: list[RuntimeCovariateDescriptor],
    shap_supported: bool,
) -> RuntimeFeatureFactorySummary:
    feature_nodes = [node for node in lineage if node.family != "target"]
    generated_nodes = [node for node in feature_nodes if node.featureType == "generated"]
    selected_nodes = [node for node in feature_nodes if node.lifecycle in {"selected", "used", "important"}]
    dropped_nodes = [node for node in feature_nodes if node.lifecycle == "dropped"]
    important_nodes = [node for node in feature_nodes if node.lifecycle == "important" or node.important]
    return RuntimeFeatureFactorySummary(
        rawColumnCount=raw_column_count,
        generatedFeatureCount=len(generated_nodes),
        userCovariateCount=len(covariates),
        selectedFeatureCount=len(selected_nodes),
        droppedFeatureCount=len(dropped_nodes),
        importantFeatureCount=len(important_nodes),
        shapSupportedFeatureCount=len(selected_nodes) if shap_supported else 0,
    )


def _build_feature_machines(
    *,
    target_column: str,
    feature_config: dict[str, Any],
    lineage: list[RuntimeFeatureNode],
    covariates: list[RuntimeCovariateDescriptor],
) -> list[RuntimeFeatureMachine]:
    machine_specs = [
        ("calendar_generator", "日历特征生成器", "generator"),
        ("lag_generator", "滞后特征生成器", "generator"),
        ("rolling_generator", "滚动统计生成器", "generator"),
        ("holiday_generator", "节假日生成器", "generator"),
        ("covariate_loader", "协变量加载器", "loader"),
    ]
    machines: list[RuntimeFeatureMachine] = []
    for machine_id, label, kind in machine_specs:
        machine_nodes = [node for node in lineage if node.machineId == machine_id]
        enabled = machine_id == "covariate_loader" and bool(feature_config.get("covariates", True)) or bool(
            feature_config.get(
                {
                    "calendar_generator": "calendarFeatures",
                    "lag_generator": "lagFeatures",
                    "rolling_generator": "rollingFeatures",
                    "holiday_generator": "holidayFeatures",
                }.get(machine_id, ""),
                False,
            )
        )
        input_columns = (
            ["Date"]
            if machine_id == "calendar_generator"
            else [target_column]
            if machine_id in {"lag_generator", "rolling_generator"}
            else [item.name for item in covariates]
            if machine_id == "covariate_loader"
            else ["Holiday Calendar"]
        )
        generated_features = [node.name for node in machine_nodes]
        summary = f"输入 {len(input_columns)} 个来源，输出 {len(generated_features)} 个特征。"
        warnings = [item.note for item in covariates if item.note and machine_id == "covariate_loader"]
        machines.append(
            RuntimeFeatureMachine(
                id=machine_id,
                label=label,
                kind=kind,  # type: ignore[arg-type]
                enabled=enabled,
                status="completed",
                inputColumns=input_columns,
                generatedFeatures=generated_features,
                summary=summary,
                durationSeconds=0.0,
                warnings=[warning for warning in warnings if warning],
            )
        )
    return machines


def _build_feature_selection(lineage: list[RuntimeFeatureNode]) -> RuntimeFeatureSelectionSummary:
    feature_nodes = [node for node in lineage if node.family != "target"]
    selected_nodes = [node for node in feature_nodes if node.lifecycle in {"selected", "used", "important"}]
    dropped_nodes = [node for node in feature_nodes if node.lifecycle == "dropped"]
    items = [
        RuntimeFeatureSelectionItem(name=node.name, status="selected", reason=None)
        for node in selected_nodes
    ] + [
        RuntimeFeatureSelectionItem(name=node.name, status="dropped", reason=node.droppedReason)
        for node in dropped_nodes
    ]
    return RuntimeFeatureSelectionSummary(
        generatedCount=len(feature_nodes),
        selectedCount=len(selected_nodes),
        droppedCount=len(dropped_nodes),
        items=items,
    )


def _resource_from_manifest(manifest: dict[str, Any], device: str) -> RuntimeResourceSnapshot:
    environment = manifest.get("environment") or {}
    total_mb = _safe_int(environment.get("memoryTotalMb"))
    available_mb = _safe_int(environment.get("memoryAvailableMb"))
    used_mb = None
    if total_mb is not None and available_mb is not None:
        used_mb = round(max(float(total_mb - available_mb), 0.0), 2)
    lowered = str(device or "cpu").lower()
    gpu_label = "GPU" if "cuda" in lowered or "gpu" in lowered else "Apple Silicon GPU" if "mps" in lowered else None
    return RuntimeResourceSnapshot(
        device=str(device or environment.get("device") or "cpu"),
        memoryTotalMb=total_mb,
        memoryAvailableMb=available_mb,
        memoryUsedMb=used_mb,
        cpuPercent=None,
        threadCount=None,
        gpuLabel=gpu_label,
    )


def _target_warnings(target_profile: dict[str, Any]) -> list[str]:
    warnings = target_profile.get("warnings") or []
    return [str(item) for item in warnings if item]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _metric_value(metrics: Any, key: str) -> float | None:
    if not isinstance(metrics, dict):
        return None
    return _safe_float(metrics.get(key))
