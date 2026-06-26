from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError, as_http_error
from app.db.models import ExperimentRecord, ReportRecord
from app.db.session import get_db
from app.schemas import GenerateReportRequest, ReportResponse
from app.services.deepseek import build_report_context, generate_deepseek_report


router = APIRouter(prefix="/api/reports", tags=["reports"])


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _experiment_payload(record: ExperimentRecord) -> dict:
    return {
        "experimentId": record.id,
        "experimentName": record.name,
        "fileName": record.file_name,
        "sheetName": record.sheet_name,
        "targetColumn": record.target_column,
        "recommendedModelId": record.recommended_model_id,
        "bestMae": float(record.best_mae) if record.best_mae is not None else None,
        "createdAt": record.created_at.isoformat(),
        "config": _loads(record.config_json, {}),
        "dataProfile": _loads(record.data_profile_json, {}),
        "rankedModels": _loads(record.metrics_json, []),
        "backtest": _loads(record.backtest_json, {}),
        "diagnostics": _loads(record.diagnostics_json, {}),
        "finalForecast": _loads(record.final_forecast_json, None),
        "modelLogs": _loads(record.model_logs_json, []),
    }


@router.post("/generate", response_model=ReportResponse)
def generate_report(request: GenerateReportRequest, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, request.experimentId)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        context = build_report_context(_experiment_payload(record))
        content = generate_deepseek_report(
            api_key=request.apiKey,
            base_url=request.baseUrl,
            model=request.model,
            context=context,
            options=request.reportOptions,
        )
        report = ReportRecord(
            id=f"report_{uuid.uuid4().hex[:12]}",
            experiment_id=record.id,
            content_markdown=content,
            model=request.model,
        )
        db.add(report)
        db.commit()
        return ReportResponse(
            reportId=report.id,
            experimentId=record.id,
            contentMarkdown=report.content_markdown,
            createdAt=report.created_at.isoformat(),
            model=report.model,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc
