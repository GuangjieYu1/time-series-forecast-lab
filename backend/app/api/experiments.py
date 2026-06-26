from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, as_http_error
from app.db.models import ExperimentRecord, ReportRecord
from app.db.session import get_db
from app.schemas import ExperimentDetail, ExperimentListItem


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


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
