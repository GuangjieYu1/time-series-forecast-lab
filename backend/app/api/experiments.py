from __future__ import annotations

import json
from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, get_workspace_context, get_workspace_experiment, require_workspace_write_access
from app.core.errors import AppError, as_http_error
from app.core.storage import assert_upload_ownership, read_upload_metadata
from app.db.models import ExperimentRecord, ReportRecord, UserRecord, WorkspaceRecord
from app.db.session import get_db
from app.schemas import (
    ExperimentExplainabilityResponse,
    ExperimentDetail,
    ExperimentListItem,
    ExperimentManifest,
    ExperimentRerunFileMatch,
    ExperimentRerunRequest,
    ExperimentRerunResponse,
    FeatureFactoryResponse,
)
from app.services.explainability import load_experiment_explainability
from app.services.data_health import build_data_health_report, extract_detected_frequency
from app.services.runtime_history import load_runtime_from_record


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.post("/rerun", response_model=ExperimentRerunResponse)
def prepare_rerun(
    request: ExperimentRerunRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        record = get_workspace_experiment(db, request.experimentId, context)
        if not record.manifest_json:
            raise AppError("This experiment does not have a reproducibility manifest yet.", 404, "MANIFEST_NOT_FOUND")
        manifest = ExperimentManifest.model_validate(_loads(record.manifest_json, {}))
        template = _loads(record.config_json, {})
        template.pop("runId", None)
        template.pop("uploadId", None)
        template["sheetName"] = manifest.data.sheetName
        match = ExperimentRerunFileMatch(warnings=["请重新上传源文件后再确认运行。"])
        if request.uploadId:
            metadata = read_upload_metadata(request.uploadId)
            assert_upload_ownership(metadata, user_id=context.user.id, workspace_id=context.workspace.id)
            file_name_matches = metadata["fileName"] == manifest.data.fileName
            sha_matches = metadata["fileSha256"] == manifest.data.fileSha256
            warnings = []
            if not file_name_matches:
                warnings.append("上传文件名与原实验不同，结果可能无法完全复现。")
            if not sha_matches:
                warnings.append("上传文件 SHA256 与原实验不同，结果可能无法完全复现。")
            match = ExperimentRerunFileMatch(
                uploadId=request.uploadId,
                uploadedFileName=metadata["fileName"],
                uploadedFileSha256=metadata["fileSha256"],
                fileNameMatches=file_name_matches,
                sha256Matches=sha_matches,
                exactMatch=file_name_matches and sha_matches,
                warnings=warnings,
            )
        return ExperimentRerunResponse(
            experimentId=record.id,
            configHash=manifest.configHash,
            sourceFileSha256=manifest.sourceFileSha256,
            manifest=manifest,
            runRequestTemplate=template,
            fileMatch=match,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("", response_model=list[ExperimentListItem])
def list_experiments(context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    rows = db.execute(
        select(ExperimentRecord, WorkspaceRecord, UserRecord)
        .join(WorkspaceRecord, WorkspaceRecord.id == ExperimentRecord.workspace_id)
        .join(UserRecord, UserRecord.id == ExperimentRecord.created_by_user_id)
        .where(ExperimentRecord.workspace_id == context.workspace.id)
        .order_by(ExperimentRecord.created_at.desc())
    ).all()
    return [
        ExperimentListItem(
            experimentId=record.id,
            experimentName=record.name,
            fileName=record.file_name,
            sheetName=record.sheet_name,
            targetColumn=record.target_column,
            modelCount=int(record.model_count or 0),
            recommendedModelId=record.recommended_model_id,
            bestMae=float(record.best_mae) if record.best_mae is not None else None,
            createdAt=record.created_at.isoformat(),
            workspaceId=workspace.id,
            workspaceName=workspace.name,
            createdByUserId=user.id,
            createdByUsername=user.username,
        )
        for record, workspace, user in rows
    ]


@router.get("/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(experiment_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        created_by = db.get(UserRecord, record.created_by_user_id)
        reports = db.scalars(
            select(ReportRecord)
            .where(ReportRecord.experiment_id == experiment_id, ReportRecord.workspace_id == context.workspace.id)
            .order_by(ReportRecord.created_at.desc())
        ).all()
        config = _loads(record.config_json, {})
        data_profile = _loads(record.data_profile_json, {})
        manifest = _loads(record.manifest_json, None)
        diagnostics = _loads(record.diagnostics_json, {})
        model_logs = _loads(record.model_logs_json, [])
        data_health = build_data_health_report(
            diagnostics,
            detected_frequency=extract_detected_frequency(data_profile=data_profile, manifest=manifest),
            horizon=_to_int(config.get("horizon"), 1) if isinstance(config, dict) else 1,
            test_size=_to_int(config.get("testSize"), 1) if isinstance(config, dict) else 1,
        )
        return ExperimentDetail(
            experimentId=record.id,
            experimentName=record.name,
            fileName=record.file_name,
            sheetName=record.sheet_name,
            targetColumn=record.target_column,
            recommendedModelId=record.recommended_model_id,
            bestMae=float(record.best_mae) if record.best_mae is not None else None,
            createdAt=record.created_at.isoformat(),
            workspaceId=context.workspace.id,
            workspaceName=context.workspace.name,
            createdByUserId=record.created_by_user_id,
            createdByUsername=created_by.username if created_by else None,
            config=config,
            dataProfile=data_profile,
            rankedModels=_loads(record.metrics_json, []),
            backtest=_loads(record.backtest_json, {}),
            diagnostics=diagnostics,
            dataHealth=data_health.model_dump() if data_health else None,
            series=_loads(record.series_json, []),
            finalForecast=_loads(record.final_forecast_json, None),
            modelLogs=model_logs,
            explainability=load_experiment_explainability(
                experiment_id=record.id,
                recommended_model_id=record.recommended_model_id,
                model_logs=model_logs,
            ),
            runtime=load_runtime_from_record(record),
            manifest=manifest,
            configHash=record.config_hash,
            sourceFileSha256=record.source_file_sha256,
            appVersion=record.app_version,
            gitCommit=record.git_commit,
            reports=[
                {
                    "reportId": report.id,
                    "experimentId": report.experiment_id,
                    "contentMarkdown": report.content_markdown,
                    "createdAt": report.created_at.isoformat(),
                    "model": report.model,
                    "workspaceId": report.workspace_id,
                    "workspaceName": context.workspace.name,
                    "createdByUserId": report.created_by_user_id,
                    "createdByUsername": (db.get(UserRecord, report.created_by_user_id).username if db.get(UserRecord, report.created_by_user_id) else None),
                }
                for report in reports
            ],
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/manifest", response_model=ExperimentManifest)
def get_experiment_manifest(experiment_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        if not record.manifest_json:
            raise AppError("This experiment does not have a reproducibility manifest yet.", 404, "MANIFEST_NOT_FOUND")
        return ExperimentManifest.model_validate(_loads(record.manifest_json, {}))
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/feature-factory", response_model=FeatureFactoryResponse)
def get_experiment_feature_factory(experiment_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        runtime = load_runtime_from_record(record)
        return FeatureFactoryResponse(
            experimentId=record.id,
            targets=runtime.featurePipeline if runtime else [],
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/explainability", response_model=ExperimentExplainabilityResponse)
def get_experiment_explainability(experiment_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        return load_experiment_explainability(
            experiment_id=record.id,
            recommended_model_id=record.recommended_model_id,
            model_logs=_loads(record.model_logs_json, []),
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/manifest/download")
def download_experiment_manifest(experiment_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        if not record.manifest_json:
            raise AppError("This experiment does not have a reproducibility manifest yet.", 404, "MANIFEST_NOT_FOUND")
        payload = json.dumps(_loads(record.manifest_json, {}), ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"{record.id}_manifest.json"
        return StreamingResponse(
            BytesIO(payload),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.delete("/{experiment_id}")
def delete_experiment(experiment_id: str, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        record = get_workspace_experiment(db, experiment_id, context)
        for report in db.scalars(select(ReportRecord).where(ReportRecord.experiment_id == experiment_id, ReportRecord.workspace_id == context.workspace.id)).all():
            db.delete(report)
        db.delete(record)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        raise as_http_error(exc) from exc
