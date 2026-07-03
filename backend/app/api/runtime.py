from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
    RuntimeEstimateRequest,
    RuntimeEstimateResponse,
    RuntimeFeaturePipelineResponse,
    RuntimeLogsResponse,
    RuntimeOptimizationResponse,
    RuntimeRunDetail,
    RuntimeTimelineResponse,
)
from app.services.model_registry import MODEL_CAPABILITIES
from app.services.runtime_estimator import estimate_runtime
from app.services.runtime_history import load_runtime_from_record
from app.services.runtime_tracker import runtime_tracker


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.post("/estimate", response_model=RuntimeEstimateResponse)
def runtime_estimate(request: RuntimeEstimateRequest, db: Session = Depends(get_db)):
    unknown_models = [model_id for model_id in request.selectedModels if model_id not in MODEL_CAPABILITIES]
    if unknown_models:
        raise AppError(
            f"未知模型：{', '.join(unknown_models)}。",
            code="UNKNOWN_MODEL",
            details={"unknownModels": unknown_models},
        )
    return estimate_runtime(request, db)


def _load_runtime_detail(runtime_id: str, db: Session) -> RuntimeRunDetail:
    live = runtime_tracker.get(runtime_id)
    if live is not None:
        return live
    record = db.get(ExperimentRecord, runtime_id)
    if record is None:
        raise AppError("Runtime detail was not found.", 404, "RUNTIME_NOT_FOUND")
    detail = load_runtime_from_record(record)
    if detail is None:
        raise AppError("Runtime detail was not found.", 404, "RUNTIME_NOT_FOUND")
    return detail


@router.get("/{runtime_id}", response_model=RuntimeRunDetail)
def runtime_detail(runtime_id: str, db: Session = Depends(get_db)):
    return _load_runtime_detail(runtime_id, db)


@router.get("/{runtime_id}/logs", response_model=RuntimeLogsResponse)
def runtime_logs(runtime_id: str, db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, db)
    return RuntimeLogsResponse(runId=detail.runId, logs=detail.logs)


@router.get("/{runtime_id}/feature-pipeline", response_model=RuntimeFeaturePipelineResponse)
def runtime_feature_pipeline(runtime_id: str, db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, db)
    return RuntimeFeaturePipelineResponse(runId=detail.runId, targets=detail.featurePipeline)


@router.get("/{runtime_id}/optimization", response_model=RuntimeOptimizationResponse)
def runtime_optimization(runtime_id: str, db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, db)
    return RuntimeOptimizationResponse(runId=detail.runId, models=detail.optimization)


@router.get("/{runtime_id}/timeline", response_model=RuntimeTimelineResponse)
def runtime_timeline(runtime_id: str, db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, db)
    return RuntimeTimelineResponse(runId=detail.runId, timeline=detail.timeline)
