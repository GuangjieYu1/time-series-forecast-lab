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

from app.core.config import get_settings
from app.core.errors import AppError, as_http_error
from app.core.storage import delete_upload, read_upload_metadata
from app.core.constants import APP_VERSION
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
    ExperimentManifest,
    FinalForecastRequest,
    FinalForecastResponse,
    ForecastProgress,
    ForecastRunRequest,
    ForecastRunResponse,
    ModelProgress,
    TargetResult,
)
from app.services.backtest_runner import ModelProgressEvent, run_holdout_backtest
from app.services.file_parser import read_sheet_dataframe
from app.services.forecast_runner import run_final_forecast
from app.services.model_registry import MODEL_CAPABILITIES, MODEL_FACTORIES
from app.services.progress_tracker import progress_tracker
from app.services.reproducibility import build_manifest
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
def get_forecast_progress(run_id: str):
    progress = progress_tracker.get(run_id)
    if progress is None:
        raise AppError("Forecast progress was not found.", 404, "PROGRESS_NOT_FOUND")
    return progress


@router.get("/progress/{run_id}/events")
async def forecast_progress_events(run_id: str, request: Request):
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
def run_forecast(request: ForecastRunRequest, db: Session = Depends(get_db)):
    run_id = request.runId or f"run_{uuid.uuid4().hex}"
    progress_tracker.start(run_id, "backtest", [], "正在校验实验配置。")
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
        progress_tracker.start(run_id, "backtest", model_rows, "正在校验实验配置。")
        metadata = read_upload_metadata(request.uploadId)
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
        df = read_sheet_dataframe(request.uploadId, request.sheetName)
        progress_tracker.update(run_id, phase="profiling", overallPercent=8, message="文件解析完成，正在清洁并构建时间序列。")

        target_results: list[TargetResult] = []
        series_profiles: list[dict] = []
        model_logs: list[dict] = []
        target_contexts: list[dict] = []
        model_count = len(request.selectedModels)
        total_model_runs = max(len(request.targetColumns) * model_count, 1)
        stage_fraction = {"fitting": 0.4, "predicting": 0.7, "scoring": 0.9, "success": 1.0, "failed": 1.0}
        stage_status = {
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
            build = build_time_series(df, request, target_column)

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

            backtest = run_holdout_backtest(
                build.series,
                request.selectedModels,
                request.horizon,
                request.testSize,
                model_parameters=request.modelParameters,
                parameter_strategy=request.parameterStrategy,
                run_profile=request.runProfile,
                random_seed=request.randomSeed,
                progress_callback=report_model_progress,
            )
            target_result = TargetResult(
                targetColumn=target_column,
                detectedFrequency=build.series.frequency,
                recommendedModelId=backtest.recommendedModelId,
                rankedModels=backtest.rankedModels,
                backtest=backtest.backtest,
                diagnostics=build.series.diagnostics,
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
                    "status": model.status,
                    "warnings": model.warnings,
                    "error": model.error,
                    "runtime": model.runtime.model_dump(),
                    "tuning": model.tuning.model_dump() if model.tuning else None,
                }
                for model in backtest.rankedModels
            )

        first = target_results[0]
        progress_tracker.update(run_id, phase="ranking", overallPercent=92, message="模型回测完成，正在生成排行榜。")
        experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
        name = request.experimentName or f"{metadata['fileName']} - {first.targetColumn} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        best = next((item for item in first.rankedModels if item.rank == 1 and item.metrics), None)
        manifest = build_manifest(
            experiment_id=experiment_id,
            experiment_name=name,
            request=request,
            upload_metadata=metadata,
            input_columns=[str(column) for column in df.columns],
            target_results=target_results,
            target_contexts=target_contexts,
            repo_root=get_settings().backend_dir.parent,
        )
        record = ExperimentRecord(
            id=experiment_id,
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
            manifest_json=_dump(manifest),
            config_hash=manifest.configHash,
            source_file_sha256=metadata["fileSha256"],
            app_version=APP_VERSION,
            git_commit=manifest.environment.gitCommit,
        )
        db.add(record)
        progress_tracker.update(run_id, phase="saving", overallPercent=97, message="正在保存实验摘要和图表数据。")
        db.commit()

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
            targetResults=target_results,
        )
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
        error = AppError(str(exc), 500, "FORECAST_RUN_FAILED")
        raise as_http_error(error) from exc
    finally:
        if cleanup_upload:
            delete_upload(request.uploadId)


@router.post("/final", response_model=FinalForecastResponse)
def final_forecast(request: FinalForecastRequest, db: Session = Depends(get_db)):
    run_id = request.runId or f"run_{uuid.uuid4().hex}"
    try:
        record = db.get(ExperimentRecord, request.experimentId)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        capability = MODEL_CAPABILITIES.get(request.finalModelId)
        progress_tracker.start(
            run_id,
            "final",
            [
                ModelProgress(
                    modelId=request.finalModelId,
                    modelName=capability.name if capability else request.finalModelId,
                    targetColumn=record.target_column,
                )
            ],
            "正在读取完整历史数据。",
        )
        data_profile = json.loads(record.data_profile_json)
        first_profile = data_profile["targets"][0]
        history = json.loads(record.series_json)
        saved_config = json.loads(record.config_json)

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

        response = run_final_forecast(
            experiment_id=request.experimentId,
            final_model_id=request.finalModelId,
            horizon=request.horizon,
            frequency=first_profile["detectedFrequency"],
            history=history,
            model_parameters=_selected_model_parameters_for_final_forecast(record, request.finalModelId, saved_config),
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
        record.final_forecast_json = _dump(response)
        db.add(record)
        db.commit()
        progress_tracker.finish(run_id, "completed", "最终预测完成。")
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
        error = AppError(str(exc), 500, "FINAL_FORECAST_FAILED")
        raise as_http_error(error) from exc
