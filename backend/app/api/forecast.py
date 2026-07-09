from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    WorkspaceContext,
    ensure_progress_scope,
    get_workspace_context,
    get_workspace_experiment,
    require_workspace_write_access,
)
from app.core.config import get_settings
from app.core.errors import AppError, as_http_error
from app.core.gpu import get_device
from app.core.storage import assert_upload_ownership, delete_upload, read_upload_metadata
from app.core.constants import APP_VERSION
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
    CovariateConfig,
    ExperimentManifest,
    FinalForecastRequest,
    FinalForecastResponse,
    ForecastProgress,
    ForecastRunRequest,
    ForecastRunResponse,
    HolidayConfig,
    ModelProgress,
    RuntimeEstimateRequest,
    TargetResult,
)
from app.services.backtest_runner import ModelProgressEvent, run_holdout_backtest
from app.services.data_health import build_data_health_report
from app.services.file_parser import read_sheet_dataframe
from app.services.feature_factory import build_feature_factory
from app.services.forecast_runner import run_final_forecast
from app.services.model_registry import MODEL_CAPABILITIES, MODEL_FACTORIES
from app.services.progress_tracker import progress_tracker
from app.services.reproducibility import build_manifest
from app.services.attribution_snapshot import build_attribution_snapshot
from app.services.runtime_estimator import estimate_runtime
from app.services.runtime_history import build_feature_pipeline_target
from app.services.runtime_state_machine import stage_from_phase
from app.services.runtime_tracker import runtime_tracker
from app.services.series_builder import build_time_series


router = APIRouter(prefix="/api/forecast", tags=["forecast"])
logger = logging.getLogger(__name__)

MAX_TARGET_COLUMNS = 8
MAX_MODEL_RUNS = 32
MAX_HEAVY_MODEL_RUNS = 4
HEAVY_MODEL_IDS = {"prophet", "timesfm"}


def _validate_run_budget(request: ForecastRunRequest) -> None:
    if not request.targetColumns:
        raise AppError("请选择至少一个预测目标列。", code="NO_TARGET_COLUMNS")
    if not request.selectedModels:
        raise AppError("请选择至少一个可运行模型。", code="NO_MODELS_SELECTED")
    if request.timeColumn in request.targetColumns:
        raise AppError("时间列不能同时作为预测目标列。", code="TIME_COLUMN_AS_TARGET")

    covariate_overlap = sorted(set(request.covariateColumns) & ({request.timeColumn} | set(request.targetColumns)))
    if covariate_overlap:
        raise AppError(
            f"协变量不能与时间列或目标列重复：{', '.join(covariate_overlap)}。",
            code="INVALID_COVARIATE_SELECTION",
            details={"overlapColumns": covariate_overlap},
        )

    unknown_models = [model_id for model_id in request.selectedModels if model_id not in MODEL_CAPABILITIES]
    if unknown_models:
        raise AppError(
            f"未知模型：{', '.join(unknown_models)}。",
            code="UNKNOWN_MODEL",
            details={"unknownModels": unknown_models},
        )

    disconnected_models = [model_id for model_id in request.selectedModels if model_id not in MODEL_FACTORIES]
    if disconnected_models:
        names = [MODEL_CAPABILITIES[model_id].name for model_id in disconnected_models]
        raise AppError(
            f"这些模型还没有接入执行器：{', '.join(names)}。",
            code="MODEL_NOT_RUNNABLE",
            details={"models": disconnected_models},
        )
    feature_models = [model_id for model_id in request.selectedModels if MODEL_CAPABILITIES[model_id].supportsCovariates]
    if feature_models and not any(request.featureConfig.model_dump().values()):
        raise AppError(
            "当前已选择需要特征工程的模型，请至少启用一种特征族。",
            code="NO_FEATURES_ENABLED",
            details={"models": feature_models},
        )

    target_count = len(request.targetColumns)
    model_count = len(request.selectedModels)
    total_model_runs = target_count * model_count
    heavy_model_runs = target_count * sum(1 for model_id in request.selectedModels if model_id in HEAVY_MODEL_IDS)

    if target_count > MAX_TARGET_COLUMNS:
        raise AppError(
            f"一次实验最多选择 {MAX_TARGET_COLUMNS} 个目标列；宽表请分批运行。",
            code="TOO_MANY_TARGET_COLUMNS",
            details={"targetCount": target_count, "maxTargetColumns": MAX_TARGET_COLUMNS},
        )
    if total_model_runs > MAX_MODEL_RUNS:
        raise AppError(
            f"一次实验最多运行 {MAX_MODEL_RUNS} 个目标-模型组合；当前是 {total_model_runs} 个，请减少目标列或模型。",
            code="TOO_MANY_MODEL_RUNS",
            details={
                "targetCount": target_count,
                "modelCount": model_count,
                "modelRunCount": total_model_runs,
                "maxModelRuns": MAX_MODEL_RUNS,
            },
        )
    if heavy_model_runs > MAX_HEAVY_MODEL_RUNS:
        raise AppError(
            f"Prophet / TimesFM 属于重模型，一次最多运行 {MAX_HEAVY_MODEL_RUNS} 个重模型组合；当前是 {heavy_model_runs} 个。",
            code="TOO_MANY_HEAVY_MODEL_RUNS",
            details={"heavyModelRunCount": heavy_model_runs, "maxHeavyModelRuns": MAX_HEAVY_MODEL_RUNS},
        )


def _dump(value) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=True)


def _runtime_stage_for_model_event(event: ModelProgressEvent) -> str:
    return {
        "covariates": "feature_engineering",
        "tuning": "auto_tuning",
        "fitting": "training",
        "predicting": "forecast",
        "scoring": "residual_analysis",
        "success": "finished",
        "failed": "failed",
    }.get(event.stage, "pending")


def _selected_model_parameters_for_final_forecast(
    record: ExperimentRecord,
    final_model_id: str,
    saved_config: dict,
) -> dict[str, dict]:
    if record.manifest_json:
        try:
            manifest = ExperimentManifest.model_validate(json.loads(record.manifest_json))
            for target in manifest.targets:
                if target.targetColumn != record.target_column:
                    continue
                for model in target.models:
                    if model.modelId == final_model_id and model.tuning and model.tuning.get("selectedParams"):
                        return {final_model_id: model.tuning["selectedParams"]}
        except Exception:
            logger.warning("manifest parse failed when restoring final model parameters", exc_info=True)
    return saved_config.get("modelParameters", {})


@router.get("/progress/{run_id}", response_model=ForecastProgress)
def get_forecast_progress(run_id: str, context: WorkspaceContext = Depends(get_workspace_context)):
    ensure_progress_scope(run_id, context)
    progress = progress_tracker.get(run_id)
    if progress is None:
        raise AppError("Forecast progress was not found.", 404, "PROGRESS_NOT_FOUND")
    return progress


@router.get("/progress/{run_id}/events")
async def forecast_progress_events(run_id: str, request: Request, context: WorkspaceContext = Depends(get_workspace_context)):
    missing_scope_checks = 0
    while True:
        scope = progress_tracker.get_scope(run_id)
        if scope is not None:
            if scope["workspaceId"] != context.workspace.id or scope["userId"] != context.user.id:
                raise AppError("这个运行实例不属于当前工作区。", 403, "PROGRESS_WORKSPACE_FORBIDDEN")
            break
        if await request.is_disconnected():
            async def empty_stream():
                if False:
                    yield ""
            return StreamingResponse(
                empty_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        missing_scope_checks += 1
        if missing_scope_checks >= 40:
            raise AppError("Forecast progress was not found.", 404, "PROGRESS_NOT_FOUND")
        await asyncio.sleep(0.25)

    async def event_stream():
        last_version = -1
        missing_checks = 0
        while not await request.is_disconnected():
            progress = progress_tracker.get(run_id)
            if progress is None:
                missing_checks += 1
                if missing_checks >= 40:
                    return
                await asyncio.sleep(0.25)
                continue
            for event in progress_tracker.get_after(run_id, last_version):
                payload = json.dumps(jsonable_encoder(event), ensure_ascii=False)
                yield f"data: {payload}\n\n"
                last_version = event.version
                if event.status in {"completed", "failed"}:
                    return
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/run", response_model=ForecastRunResponse)
def run_forecast(request: ForecastRunRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    run_id = request.runId or f"run_{uuid.uuid4().hex}"
    progress_tracker.start(run_id, "backtest", [], "正在校验实验配置。", user_id=context.user.id, workspace_id=context.workspace.id)
    runtime_tracker.start(
        run_id,
        kind="backtest",
        model_rows=[],
        message="正在校验实验配置。",
        device=get_device(),
        parameter_strategy=request.parameterStrategy,
        user_id=context.user.id,
        workspace_id=context.workspace.id,
    )
    cleanup_upload = False
    metadata = None
    try:
        _validate_run_budget(request)
        model_rows = [
            ModelProgress(
                modelId=model_id,
                modelName=MODEL_CAPABILITIES[model_id].name,
                targetColumn=target_column,
            )
            for target_column in request.targetColumns
            for model_id in request.selectedModels
        ]
        progress_tracker.start(run_id, "backtest", model_rows, "正在校验实验配置。", user_id=context.user.id, workspace_id=context.workspace.id)
        runtime_tracker.start(
            run_id,
            kind="backtest",
            model_rows=model_rows,
            message="正在校验实验配置。",
            device=get_device(),
            parameter_strategy=request.parameterStrategy,
            user_id=context.user.id,
            workspace_id=context.workspace.id,
        )
        metadata = read_upload_metadata(request.uploadId)
        assert_upload_ownership(metadata, user_id=context.user.id, workspace_id=context.workspace.id)
        logger.info(
            "forecast run started run_id=%s upload_id=%s file=%s sheet=%s targets=%s models=%s horizon=%s test_size=%s",
            run_id,
            request.uploadId,
            metadata.get("fileName"),
            request.sheetName,
            request.targetColumns,
            request.selectedModels,
            request.horizon,
            request.testSize,
        )
        cleanup_upload = True
        progress_tracker.update(run_id, phase="parsing", overallPercent=4, message="正在读取上传文件和 Sheet。")
        runtime_tracker.set_overall(
            run_id,
            stage=stage_from_phase("parsing"),
            message="正在读取上传文件和 Sheet。",
            overall_percent=4,
        )
        df = read_sheet_dataframe(request.uploadId, request.sheetName)
        try:
            runtime_estimate = estimate_runtime(
                RuntimeEstimateRequest(
                    rowCount=max(len(df), 1),
                    frequency="auto",
                    totalColumnCount=max(len(df.columns), 1),
                    targetCount=max(len(request.targetColumns), 1),
                    covariateCount=len(request.covariateColumns),
                    featureConfig=request.featureConfig,
                    runProfile=request.runProfile,
                    parameterStrategy=request.parameterStrategy,
                    device=get_device(),
                    selectedModels=request.selectedModels,
                ),
                db,
            )
            target_count = max(len(request.targetColumns), 1)
            runtime_tracker.set_estimates(
                run_id,
                estimated_total_seconds=round(sum(item.estimatedSeconds for item in runtime_estimate.models), 4),
                estimated_model_seconds={
                    (target_column, item.id): round(item.estimatedSeconds / target_count, 4)
                    for target_column in request.targetColumns
                    for item in runtime_estimate.models
                },
                compute_targets={item.id: item.computeTarget for item in runtime_estimate.models},
            )
        except Exception:
            logger.warning("runtime estimate unavailable during run bootstrap", exc_info=True)
        progress_tracker.update(run_id, phase="profiling", overallPercent=8, message="文件解析完成，正在清洁并构建时间序列。")
        runtime_tracker.set_overall(
            run_id,
            stage=stage_from_phase("profiling"),
            message="文件解析完成，正在清洁并构建时间序列。",
            overall_percent=8,
        )

        target_results: list[TargetResult] = []
        series_profiles: list[dict] = []
        model_logs: list[dict] = []
        target_contexts: list[dict] = []
        model_count = len(request.selectedModels)
        total_model_runs = max(len(request.targetColumns) * model_count, 1)
        stage_fraction = {"covariates": 0.03, "fitting": 0.4, "predicting": 0.7, "scoring": 0.9, "success": 1.0, "failed": 1.0}
        stage_status = {
            "covariates": ("queued", 5, "正在准备未来协变量。"),
            "tuning": ("tuning", None, "正在自动优化参数。"),
            "fitting": ("fitting", 10, "正在拟合训练集。"),
            "predicting": ("predicting", 55, "拟合完成，正在预测测试集。"),
            "scoring": ("scoring", 80, "预测完成，正在计算残差和指标。"),
            "success": ("success", 100, "模型运行成功。"),
            "failed": ("failed", 100, "模型运行失败，其他模型继续。"),
        }
        for target_index, target_column in enumerate(request.targetColumns):
            progress_tracker.update(
                run_id,
                phase="building_series",
                currentTarget=target_column,
                overallPercent=max(8, 10 + int((target_index * model_count / total_model_runs) * 80)),
                message=f"正在清洁目标列 {target_column} 并构建时间序列。",
            )
            runtime_tracker.set_overall(
                run_id,
                stage=stage_from_phase("building_series"),
                message=f"正在清洁目标列 {target_column} 并构建时间序列。",
                overall_percent=max(8, 10 + int((target_index * model_count / total_model_runs) * 80)),
                current_target=target_column,
            )
            build = build_time_series(df, request, target_column)
            pipeline_target = build_feature_pipeline_target(
                target_profile=build.data_profile,
                selected_model_ids=request.selectedModels,
                warnings=build.series.diagnostics.warnings,
            )
            train_points = build.series.points[:-request.testSize]
            train_covariates = build.series.covariateRows[:-request.testSize] if build.series.covariateRows else []
            runtime_tracker.set_overall(
                run_id,
                stage="feature_engineering",
                message=f"正在为目标列 {target_column} 构建共享 Feature Factory。",
                overall_percent=max(9, 11 + int((target_index * model_count / total_model_runs) * 80)),
                current_target=target_column,
            )
            feature_result = build_feature_factory(
                pipeline=pipeline_target,
                times=[point.time for point in train_points],
                values=[point.value for point in train_points],
                frequency=build.series.frequency,
                covariates=train_covariates,
                feature_config=request.featureConfig.model_dump(),
                selected_model_ids=request.selectedModels,
                holiday_config=request.holidayConfig,
                progress_callback=lambda snapshot: runtime_tracker.set_feature_pipeline(run_id, snapshot),
            )
            runtime_tracker.set_feature_pipeline(run_id, feature_result.pipeline)
            runtime_tracker.set_overall(
                run_id,
                stage="feature_selection",
                message=f"目标列 {target_column} 的特征管线已构建，正在按模型能力筛选可用特征。",
                overall_percent=max(9, 12 + int((target_index * model_count / total_model_runs) * 80)),
                current_target=target_column,
            )

            def report_model_progress(event: ModelProgressEvent, target_index=target_index, target_column=target_column):
                model_index = request.selectedModels.index(event.modelId)
                if event.stage == "tuning":
                    tuning_percent = min(100, max(0, event.progressPercent or 0))
                    fraction = 0.05 + (tuning_percent / 100) * 0.25
                    status = "tuning"
                    percent = min(35, max(5, 5 + int(tuning_percent * 0.3)))
                    message = event.message or "正在自动优化参数。"
                else:
                    fraction = stage_fraction[event.stage]
                    status, percent, message = stage_status[event.stage]
                completed_units = target_index * model_count + model_index + fraction
                overall = min(90, 10 + int((completed_units / total_model_runs) * 80))
                progress_tracker.update_model(
                    run_id,
                    target_column,
                    event.modelId,
                    status=status,
                    percent=percent,
                    message=message,
                    fitSeconds=round(event.fitSeconds, 4) if event.fitSeconds else None,
                    predictSeconds=round(event.predictSeconds, 4) if event.predictSeconds else None,
                    error=event.error,
                )
                progress_tracker.update(
                    run_id,
                    phase=f"model_{event.stage}",
                    currentTarget=target_column,
                    overallPercent=overall,
                    message=f"{MODEL_CAPABILITIES[event.modelId].name}：{message}",
                )
                runtime_tracker.set_overall(
                    run_id,
                    stage=_runtime_stage_for_model_event(event),
                    message=f"{MODEL_CAPABILITIES[event.modelId].name}：{message}",
                    overall_percent=overall,
                    current_target=target_column,
                )
                runtime_tracker.update_model(
                    run_id,
                    target_column=target_column,
                    model_id=event.modelId,
                    status=status,
                    message=message,
                    progress_percent=percent,
                    current_stage=_runtime_stage_for_model_event(event),
                    fit_seconds=round(event.fitSeconds, 4) if event.fitSeconds else None,
                    predict_seconds=round(event.predictSeconds, 4) if event.predictSeconds else None,
                    tuning_seconds=round(event.tuningSeconds, 4) if event.tuningSeconds else None,
                    error=event.error,
                    metric_label="MAE" if event.currentMetric is not None else None,
                    metric_value=event.currentMetric,
                    params=dict(event.params or {}),
                    best_metric=event.bestMetric,
                    warnings=list(event.warnings or []),
                )
                if event.stage == "tuning":
                    runtime_tracker.update_optimization(
                        run_id,
                        target_column=target_column,
                        model_id=event.modelId,
                        current_trial=event.currentTrial or 0,
                        total_trials=event.totalTrials or max(event.currentTrial or 0, 1),
                        message=message,
                        params=dict(event.params or {}),
                        current_metric=event.currentMetric,
                        best_metric=event.bestMetric,
                        tuning_seconds=round(event.tuningSeconds, 4) if event.tuningSeconds else None,
                        trial_status=event.tuningStatus or "running",
                        strategy_label=event.tuningStrategyLabel,
                        sampler=event.tuningSampler,
                        pruner=event.tuningPruner,
                    )

            backtest = run_holdout_backtest(
                build.series,
                request.selectedModels,
                request.horizon,
                request.testSize,
                model_parameters=request.modelParameters,
                parameter_strategy=request.parameterStrategy,
                run_profile=request.runProfile,
                random_seed=request.randomSeed,
                feature_config=request.featureConfig.model_dump(),
                prepared_features=feature_result.prepared,
                feature_factory_error=feature_result.error,
                progress_callback=report_model_progress,
            )
            data_health = build_data_health_report(
                build.series.diagnostics,
                detected_frequency=build.series.frequency,
                horizon=request.horizon,
                test_size=request.testSize,
            )
            if data_health is None:
                raise AppError("无法生成数据健康报告。", code="DATA_HEALTH_BUILD_FAILED")
            target_result = TargetResult(
                targetColumn=target_column,
                detectedFrequency=build.series.frequency,
                recommendedModelId=backtest.recommendedModelId,
                rankedModels=backtest.rankedModels,
                backtest=backtest.backtest,
                diagnostics=build.series.diagnostics,
                dataHealth=data_health,
            )
            target_results.append(target_result)
            series_profiles.append(build.data_profile)
            points = build.series.points
            train = points[:-request.testSize]
            test = points[-request.testSize:]
            target_contexts.append(
                {
                    "timeStart": points[0].time.isoformat() if points else None,
                    "timeEnd": points[-1].time.isoformat() if points else None,
                    "trainStart": train[0].time.isoformat() if train else None,
                    "trainEnd": train[-1].time.isoformat() if train else None,
                    "testStart": test[0].time.isoformat() if test else None,
                    "testEnd": test[-1].time.isoformat() if test else None,
                }
            )
            model_logs.extend(
                {
                    "targetColumn": target_column,
                    "modelId": model.modelId,
                    "modelName": model.modelName,
                    "status": model.status,
                    "warnings": model.warnings,
                    "error": model.error,
                    "runtime": model.runtime.model_dump(),
                    "tuning": model.tuning.model_dump() if model.tuning else None,
                    "explainability": backtest.explainabilityByModel.get(model.modelId),
                }
                for model in backtest.rankedModels
            )

        first = target_results[0]
        progress_tracker.update(run_id, phase="ranking", overallPercent=92, message="模型回测完成，正在生成排行榜。")
        runtime_tracker.set_overall(
            run_id,
            stage=stage_from_phase("ranking"),
            message="模型回测完成，正在生成排行榜。",
            overall_percent=92,
        )
        experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
        name = request.experimentName or f"{metadata['fileName']} - {first.targetColumn} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        best = next((item for item in first.rankedModels if item.rank == 1 and item.metrics), None)
        runtime_snapshot = runtime_tracker.get(run_id)
        manifest = build_manifest(
            experiment_id=experiment_id,
            experiment_name=name,
            request=request,
            upload_metadata=metadata,
            input_columns=[str(column) for column in df.columns],
            target_results=target_results,
            target_contexts=target_contexts,
            repo_root=get_settings().backend_dir.parent,
            feature_pipelines=runtime_snapshot.featurePipeline if runtime_snapshot else [],
        )
        record = ExperimentRecord(
            id=experiment_id,
            workspace_id=context.workspace.id,
            created_by_user_id=context.user.id,
            name=name,
            file_name=metadata["fileName"],
            sheet_name=request.sheetName,
            target_column=first.targetColumn,
            recommended_model_id=first.recommendedModelId,
            best_mae=str(best.metrics.mae) if best and best.metrics else None,
            model_count=str(len(request.selectedModels)),
            config_json=_dump(request),
            data_profile_json=_dump({"targets": series_profiles}),
            metrics_json=_dump(first.rankedModels),
            backtest_json=_dump(first.backtest),
            diagnostics_json=_dump(first.diagnostics),
            series_json=_dump(series_profiles[0]["history"]),
            final_forecast_json=None,
            model_logs_json=_dump(model_logs),
            runtime_json=None,
            manifest_json=_dump(manifest),
            config_hash=manifest.configHash,
            source_file_sha256=metadata["fileSha256"],
            app_version=APP_VERSION,
            git_commit=manifest.environment.gitCommit,
        )
        db.add(record)
        progress_tracker.update(run_id, phase="saving", overallPercent=97, message="正在保存实验摘要和图表数据。")
        runtime_tracker.set_overall(
            run_id,
            stage=stage_from_phase("saving"),
            message="正在保存实验摘要和图表数据。",
            overall_percent=97,
        )

        response = ForecastRunResponse(
            experimentId=experiment_id,
            targetColumn=first.targetColumn,
            detectedFrequency=first.detectedFrequency,
            horizon=request.horizon,
            testSize=request.testSize,
            recommendedModelId=first.recommendedModelId,
            rankedModels=first.rankedModels,
            backtest=first.backtest,
            diagnostics=first.diagnostics,
            dataHealth=first.dataHealth,
            targetResults=target_results,
            manifest=manifest,
        )
        runtime_snapshot = runtime_tracker.finalize(
            run_id,
            status="completed",
            message="实验完成，结果已保存。",
            experiment_id=experiment_id,
        )
        record.runtime_json = _dump(runtime_snapshot) if runtime_snapshot is not None else None
        record.attribution_json = _dump(build_attribution_snapshot(record))
        db.commit()
        progress_tracker.finish(run_id, "completed", "实验完成，结果已保存。")
        logger.info(
            "forecast run completed run_id=%s experiment_id=%s recommended_model=%s targets=%s models=%s",
            run_id,
            experiment_id,
            response.recommendedModelId,
            request.targetColumns,
            request.selectedModels,
        )
        return response
    except AppError as exc:
        logger.warning(
            "forecast run rejected run_id=%s upload_id=%s sheet=%s code=%s message=%s",
            run_id,
            request.uploadId,
            request.sheetName,
            exc.code,
            exc.message,
        )
        progress_tracker.finish(run_id, "failed", "实验运行失败。", exc.message)
        runtime_tracker.finalize(run_id, status="failed", message="实验运行失败。", error=exc.message)
        raise as_http_error(exc) from exc
    except Exception as exc:
        logger.exception(
            "forecast run failed run_id=%s upload_id=%s file=%s sheet=%s targets=%s models=%s",
            run_id,
            request.uploadId,
            metadata.get("fileName") if metadata else None,
            request.sheetName,
            request.targetColumns,
            request.selectedModels,
        )
        progress_tracker.finish(run_id, "failed", "实验运行失败。", str(exc))
        runtime_tracker.finalize(run_id, status="failed", message="实验运行失败。", error=str(exc))
        error = AppError(str(exc), 500, "FORECAST_RUN_FAILED")
        raise as_http_error(error) from exc
    finally:
        if cleanup_upload:
            delete_upload(request.uploadId)


@router.post("/final", response_model=FinalForecastResponse)
def final_forecast(request: FinalForecastRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    run_id = request.runId or f"run_{uuid.uuid4().hex}"
    try:
        record = get_workspace_experiment(db, request.experimentId, context)
        data_profile = json.loads(record.data_profile_json)
        first_profile = data_profile["targets"][0]
        history = json.loads(record.series_json)
        saved_config = json.loads(record.config_json)
        saved_manifest = json.loads(record.manifest_json) if record.manifest_json else {}
        capability = MODEL_CAPABILITIES.get(request.finalModelId)
        final_model_row = ModelProgress(
            modelId=request.finalModelId,
            modelName=capability.name if capability else request.finalModelId,
            targetColumn=record.target_column,
        )
        progress_tracker.start(
            run_id,
            "final",
            [final_model_row],
            "正在读取完整历史数据。",
            user_id=context.user.id,
            workspace_id=context.workspace.id,
        )
        runtime_tracker.start(
            run_id,
            kind="final",
            model_rows=[final_model_row],
            message="正在读取完整历史数据。",
            device=str((saved_manifest.get("environment") or {}).get("device") or get_device()),
            parameter_strategy=str(saved_config.get("parameterStrategy") or "default"),
            user_id=context.user.id,
            workspace_id=context.workspace.id,
        )
        covariate_history = [
            {key: float(value) for key, value in row.items() if key != "time" and value is not None}
            for row in first_profile.get("covariateHistory", [])
        ]
        known_future_rows = [
            {key: float(value) for key, value in row.items() if key != "time" and value is not None}
            for row in first_profile.get("futureCovariates", [])
        ]
        covariate_configs = [CovariateConfig.model_validate(item) for item in first_profile.get("covariateConfigs", [])]
        holiday_config = HolidayConfig.model_validate(first_profile.get("holidayConfig") or {})
        final_pipeline = build_feature_pipeline_target(
            target_profile=first_profile,
            selected_model_ids=[request.finalModelId],
            warnings=list(first_profile.get("warnings") or []),
        )
        final_feature_result = build_feature_factory(
            pipeline=final_pipeline,
            times=[datetime.fromisoformat(point["time"]) for point in history],
            values=[float(point["value"]) for point in history],
            frequency=first_profile["detectedFrequency"],
            covariates=covariate_history or None,
            feature_config=saved_config.get("featureConfig"),
            selected_model_ids=[request.finalModelId],
            holiday_config=holiday_config,
            progress_callback=lambda snapshot: runtime_tracker.set_feature_pipeline(run_id, snapshot),
        )
        runtime_tracker.set_feature_pipeline(run_id, final_feature_result.pipeline)
        if final_feature_result.error and request.finalModelId in {"xgboost", "lightgbm", "random_forest"}:
            raise AppError(f"Feature Factory failed: {final_feature_result.error}", code="FEATURE_FACTORY_FAILED")

        def report_final_progress(stage: str):
            if stage == "fitting":
                progress_tracker.update_model(
                    run_id,
                    record.target_column,
                    request.finalModelId,
                    status="fitting",
                    percent=20,
                    message="正在使用完整历史数据拟合模型。",
                )
                progress_tracker.update(run_id, phase="fitting", overallPercent=25, message="正在重新拟合最终模型。")
                runtime_tracker.set_overall(
                    run_id,
                    stage=stage_from_phase("fitting"),
                    message="正在重新拟合最终模型。",
                    overall_percent=25,
                    current_target=record.target_column,
                )
                runtime_tracker.update_model(
                    run_id,
                    target_column=record.target_column,
                    model_id=request.finalModelId,
                    status="fitting",
                    message="正在使用完整历史数据拟合模型。",
                    progress_percent=20,
                    current_stage="training",
                )
            else:
                progress_tracker.update_model(
                    run_id,
                    record.target_column,
                    request.finalModelId,
                    status="predicting",
                    percent=70,
                    message="模型拟合完成，正在生成未来预测。",
                )
                progress_tracker.update(run_id, phase="predicting", overallPercent=72, message="正在生成未来预测和置信区间。")
                runtime_tracker.set_overall(
                    run_id,
                    stage=stage_from_phase("predicting"),
                    message="正在生成未来预测和置信区间。",
                    overall_percent=72,
                    current_target=record.target_column,
                )
                runtime_tracker.update_model(
                    run_id,
                    target_column=record.target_column,
                    model_id=request.finalModelId,
                    status="predicting",
                    message="模型拟合完成，正在生成未来预测。",
                    progress_percent=70,
                    current_stage="forecast",
                )

        response = run_final_forecast(
            experiment_id=request.experimentId,
            final_model_id=request.finalModelId,
            horizon=request.horizon,
            frequency=first_profile["detectedFrequency"],
            history=history,
            model_parameters=_selected_model_parameters_for_final_forecast(record, request.finalModelId, saved_config),
            covariate_history=covariate_history or None,
            known_future_rows=known_future_rows or None,
            covariate_configs=covariate_configs,
            holiday_config=holiday_config,
            feature_config=saved_config.get("featureConfig"),
            prepared_features=final_feature_result.prepared,
            progress_callback=report_final_progress,
        )
        progress_tracker.update_model(
            run_id,
            record.target_column,
            request.finalModelId,
            status="success",
            percent=100,
            message="最终预测生成成功。",
        )
        progress_tracker.update(run_id, phase="saving", overallPercent=95, message="正在保存最终预测。")
        runtime_tracker.update_model(
            run_id,
            target_column=record.target_column,
            model_id=request.finalModelId,
            status="success",
            message="最终预测生成成功。",
            progress_percent=100,
            current_stage="finished",
        )
        runtime_tracker.set_overall(
            run_id,
            stage=stage_from_phase("saving"),
            message="正在保存最终预测。",
            overall_percent=95,
            current_target=record.target_column,
        )
        record.final_forecast_json = _dump(response)
        db.add(record)
        db.commit()
        progress_tracker.finish(run_id, "completed", "最终预测完成。")
        runtime_tracker.finalize(run_id, status="completed", message="最终预测完成。")
        logger.info(
            "final forecast completed run_id=%s experiment_id=%s model=%s horizon=%s",
            run_id,
            request.experimentId,
            request.finalModelId,
            request.horizon,
        )
        return response
    except AppError as exc:
        logger.warning(
            "final forecast rejected run_id=%s experiment_id=%s model=%s code=%s message=%s",
            run_id,
            request.experimentId,
            request.finalModelId,
            exc.code,
            exc.message,
        )
        progress_tracker.finish(run_id, "failed", "最终预测失败。", exc.message)
        runtime_tracker.finalize(run_id, status="failed", message="最终预测失败。", error=exc.message)
        raise as_http_error(exc) from exc
    except Exception as exc:
        logger.exception(
            "final forecast failed run_id=%s experiment_id=%s model=%s horizon=%s",
            run_id,
            request.experimentId,
            request.finalModelId,
            request.horizon,
        )
        progress_tracker.finish(run_id, "failed", "最终预测失败。", str(exc))
        runtime_tracker.finalize(run_id, status="failed", message="最终预测失败。", error=str(exc))
        error = AppError(str(exc), 500, "FINAL_FORECAST_FAILED")
        raise as_http_error(error) from exc
