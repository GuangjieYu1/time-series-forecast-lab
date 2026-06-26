from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.errors import AppError, as_http_error
from app.core.storage import delete_upload, read_upload_metadata
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
    FinalForecastRequest,
    FinalForecastResponse,
    ForecastRunRequest,
    ForecastRunResponse,
    TargetResult,
)
from app.services.backtest_runner import run_holdout_backtest
from app.services.file_parser import read_sheet_dataframe
from app.services.forecast_runner import run_final_forecast
from app.services.series_builder import build_time_series


router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def _dump(value) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=True)


@router.post("/run", response_model=ForecastRunResponse)
def run_forecast(request: ForecastRunRequest, db: Session = Depends(get_db)):
    cleanup_upload = False
    try:
        if not request.targetColumns:
            raise AppError("Select at least one target column.")
        metadata = read_upload_metadata(request.uploadId)
        cleanup_upload = True
        df = read_sheet_dataframe(request.uploadId, request.sheetName)

        target_results: list[TargetResult] = []
        series_profiles: list[dict] = []
        model_logs: list[dict] = []
        for target_column in request.targetColumns:
            build = build_time_series(df, request, target_column)
            backtest = run_holdout_backtest(build.series, request.selectedModels, request.horizon, request.testSize)
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
        db.commit()

        return ForecastRunResponse(
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
    except AppError as exc:
        raise as_http_error(exc) from exc
    finally:
        if cleanup_upload:
            delete_upload(request.uploadId)


@router.post("/final", response_model=FinalForecastResponse)
def final_forecast(request: FinalForecastRequest, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, request.experimentId)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        data_profile = json.loads(record.data_profile_json)
        first_profile = data_profile["targets"][0]
        history = json.loads(record.series_json)
        response = run_final_forecast(
            experiment_id=request.experimentId,
            final_model_id=request.finalModelId,
            horizon=request.horizon,
            frequency=first_profile["detectedFrequency"],
            history=history,
        )
        record.final_forecast_json = _dump(response)
        db.add(record)
        db.commit()
        return response
    except AppError as exc:
        raise as_http_error(exc) from exc
