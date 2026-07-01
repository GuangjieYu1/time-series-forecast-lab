from __future__ import annotations

import json
from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, as_http_error
from app.core.storage import read_upload_metadata
from app.db.models import ExperimentRecord, ReportRecord
from app.db.session import get_db
from app.schemas import ExperimentDetail, ExperimentListItem, ExperimentManifest, ExperimentRerunFileMatch, ExperimentRerunRequest, ExperimentRerunResponse


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


@router.post("/rerun", response_model=ExperimentRerunResponse)
def prepare_rerun(request: ExperimentRerunRequest, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, request.experimentId)
        if record is None:
            raise AppError("Experiment was not found.", 404)
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
def list_experiments(db: Session = Depends(get_db)):
    records = db.scalars(select(ExperimentRecord).order_by(ExperimentRecord.created_at.desc())).all()
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
        )
        for record in records
    ]


@router.get("/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(experiment_id: str, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, experiment_id)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        reports = db.scalars(
            select(ReportRecord).where(ReportRecord.experiment_id == experiment_id).order_by(ReportRecord.created_at.desc())
        ).all()
        return ExperimentDetail(
            experimentId=record.id,
            experimentName=record.name,
            fileName=record.file_name,
            sheetName=record.sheet_name,
            targetColumn=record.target_column,
            recommendedModelId=record.recommended_model_id,
            bestMae=float(record.best_mae) if record.best_mae is not None else None,
            createdAt=record.created_at.isoformat(),
            config=_loads(record.config_json, {}),
            dataProfile=_loads(record.data_profile_json, {}),
            rankedModels=_loads(record.metrics_json, []),
            backtest=_loads(record.backtest_json, {}),
            diagnostics=_loads(record.diagnostics_json, {}),
            series=_loads(record.series_json, []),
            finalForecast=_loads(record.final_forecast_json, None),
            modelLogs=_loads(record.model_logs_json, []),
            manifest=_loads(record.manifest_json, None),
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
                }
                for report in reports
            ],
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/manifest", response_model=ExperimentManifest)
def get_experiment_manifest(experiment_id: str, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, experiment_id)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        if not record.manifest_json:
            raise AppError("This experiment does not have a reproducibility manifest yet.", 404, "MANIFEST_NOT_FOUND")
        return ExperimentManifest.model_validate(_loads(record.manifest_json, {}))
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/manifest/download")
def download_experiment_manifest(experiment_id: str, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, experiment_id)
        if record is None:
            raise AppError("Experiment was not found.", 404)
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
def delete_experiment(experiment_id: str, db: Session = Depends(get_db)):
    try:
        record = db.get(ExperimentRecord, experiment_id)
        if record is None:
            raise AppError("Experiment was not found.", 404)
        for report in db.scalars(select(ReportRecord).where(ReportRecord.experiment_id == experiment_id)).all():
            db.delete(report)
        db.delete(record)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        raise as_http_error(exc) from exc
