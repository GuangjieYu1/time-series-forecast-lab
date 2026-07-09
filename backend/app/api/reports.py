from __future__ import annotations

import json
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, get_workspace_context, get_workspace_experiment, require_workspace_write_access
from app.core.errors import AppError, as_http_error
from app.db.models import ExperimentRecord, ReportRecord, UserRecord
from app.db.session import get_db
from app.schemas import GenerateReportPdfRequest, GenerateReportRequest, ReportResponse
from app.services.data_health import build_data_health_report, extract_detected_frequency
from app.services.deepseek import build_report_context, generate_deepseek_report
from app.services.report_pdf import build_report_pdf
from app.services.runtime_history import load_runtime_from_record


router = APIRouter(prefix="/api/reports", tags=["reports"])


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _experiment_payload(record: ExperimentRecord) -> dict:
    config = _loads(record.config_json, {})
    data_profile = _loads(record.data_profile_json, {})
    diagnostics = _loads(record.diagnostics_json, {})
    manifest = _loads(record.manifest_json, None)
    runtime = load_runtime_from_record(record)
    data_health = build_data_health_report(
        diagnostics,
        detected_frequency=extract_detected_frequency(data_profile=data_profile, manifest=manifest),
        horizon=_to_int(config.get("horizon"), 1) if isinstance(config, dict) else 1,
        test_size=_to_int(config.get("testSize"), 1) if isinstance(config, dict) else 1,
    )
    return {
        "experimentId": record.id,
        "experimentName": record.name,
        "fileName": record.file_name,
        "sheetName": record.sheet_name,
        "targetColumn": record.target_column,
        "recommendedModelId": record.recommended_model_id,
        "bestMae": float(record.best_mae) if record.best_mae is not None else None,
        "createdAt": record.created_at.isoformat(),
        "config": config,
        "dataProfile": data_profile,
        "rankedModels": _loads(record.metrics_json, []),
        "backtest": _loads(record.backtest_json, {}),
        "diagnostics": diagnostics,
        "dataHealth": data_health.model_dump() if data_health else None,
        "finalForecast": _loads(record.final_forecast_json, None),
        "modelLogs": _loads(record.model_logs_json, []),
        "runtime": runtime.model_dump(mode="json") if runtime else None,
        "manifest": manifest,
    }


@router.post("/generate", response_model=ReportResponse)
def generate_report(request: GenerateReportRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, request.experimentId, context)
        report_context = build_report_context(_experiment_payload(record))
        content = generate_deepseek_report(
            api_key=request.apiKey,
            base_url=request.baseUrl,
            model=request.model,
            context=report_context,
            options=request.reportOptions,
        )
        report = ReportRecord(
            id=f"report_{uuid.uuid4().hex[:12]}",
            experiment_id=record.id,
            workspace_id=record.workspace_id,
            created_by_user_id=context.user.id,
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
            workspaceId=record.workspace_id,
            workspaceName=context.workspace.name,
            createdByUserId=context.user.id,
            createdByUsername=context.user.username,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/{report_id}/pdf")
def export_report_pdf(report_id: str, request: GenerateReportPdfRequest, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        report = db.get(ReportRecord, report_id)
        if report is None:
            raise AppError("Report was not found.", 404)
        if report.workspace_id != context.workspace.id:
            raise AppError("这个报告不属于当前工作区。", 403, "REPORT_WORKSPACE_FORBIDDEN")
        pdf_bytes = build_report_pdf(
            title=(request.title or report.id).strip() or report.id,
            content_markdown=report.content_markdown,
            visual_artifacts=[artifact.model_dump() for artifact in request.visualArtifacts],
        )
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{report.id}.pdf"'},
        )
    except AppError as exc:
        raise as_http_error(exc) from exc
