from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError, as_http_error
from app.core.storage import delete_upload, read_upload_metadata
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
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
from app.services.model_registry import MODEL_CAPABILITIES
from app.services.progress_tracker import progress_tracker
from app.services.series_builder import build_time_series


router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def _dump(value) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=True)


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
    model_rows = [
        ModelProgress(
            modelId=model_id,
            modelName=MODEL_CAPABILITIES[model_id].name if model_id in MODEL_CAPABILITIES else model_id,
            targetColumn=target_column,
        )
        for target_column in request.targetColumns
        for model_id in request.selectedModels
    ]
    progress_tracker.start(run_id, "backtest", model_rows, "正在校验实验配置。")
    cleanup_upload = False
    try:
        if not request.targetColumns:
            raise AppError("Select at least one target column.")
        metadata = read_upload_metadata(request.uploadId)
        cleanup_upload = True
        progress_tracker.update(run_id, phase="parsing", overallPercent=4, message="正在读取上传文件和 Sheet。")
        df = read_sheet_dataframe(request.uploadId, request.sheetName)
        progress_tracker.update(run_id, phase="profiling", overallPercent=8, message="文件解析完成，正在清洁并构建时间序列。")

        target_results: list[TargetResult] = []
        series_profiles: list[dict] = []
        model_logs: list[dict] = []
        model_count = len(request.selectedModels)
        total_model_runs = max(len(request.targetColumns) * model_count, 1)
        stage_fraction = {"fitting": 0.1, "predicting": 0.55, "scoring": 0.8, "success": 1.0, "failed": 1.0}
        stage_status = {
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
                fraction = stage_fraction[event.stage]
                completed_units = target_index * model_count + model_index + fraction
                overall = min(90, 10 + int((completed_units / total_model_runs) * 80))
                status, percent, message = stage_status[event.stage]
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
            model_logs.extend(
                {
                    "targetColumn": target_column,
                    "modelId": model.modelId,
                    "status": model.status,
                    "warnings": model.warnings,
                    "error": model.error,
                    "runtime": model.runtime.model_dump(),
                }
                for model in backtest.rankedModels
            )

        first = target_results[0]
        progress_tracker.update(run_id, phase="ranking", overallPercent=92, message="模型回测完成，正在生成排行榜。")
        experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
        name = request.experimentName or f"{metadata['fileName']} - {first.targetColumn} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        best = next((item for item in first.rankedModels if item.rank == 1 and item.metrics), None)
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
        return response
    except AppError as exc:
        progress_tracker.finish(run_id, "failed", "实验运行失败。", exc.message)
        raise as_http_error(exc) from exc
    except Exception as exc:
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
        return response
    except AppError as exc:
        progress_tracker.finish(run_id, "failed", "最终预测失败。", exc.message)
        raise as_http_error(exc) from exc
    except Exception as exc:
        progress_tracker.finish(run_id, "failed", "最终预测失败。", str(exc))
        error = AppError(str(exc), 500, "FINAL_FORECAST_FAILED")
        raise as_http_error(error) from exc
