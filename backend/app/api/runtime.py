import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, ensure_runtime_scope, get_workspace_context
from app.core.errors import AppError
from app.db.models import ExperimentRecord
from app.db.session import get_db
from app.schemas import (
    RuntimeEstimateRequest,
    RuntimeEstimateResponse,
    RuntimeEventsResponse,
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
def runtime_estimate(request: RuntimeEstimateRequest, _: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    unknown_models = [model_id for model_id in request.selectedModels if model_id not in MODEL_CAPABILITIES]
    if unknown_models:
        raise AppError(
            f"未知模型：{', '.join(unknown_models)}。",
            code="UNKNOWN_MODEL",
            details={"unknownModels": unknown_models},
        )
    return estimate_runtime(request, db)


def _load_runtime_detail(runtime_id: str, context: WorkspaceContext, db: Session) -> RuntimeRunDetail:
    ensure_runtime_scope(runtime_id, context, db)
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
def runtime_detail(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    return _load_runtime_detail(runtime_id, context, db)


@router.get("/{runtime_id}/logs", response_model=RuntimeLogsResponse)
def runtime_logs(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, context, db)
    return RuntimeLogsResponse(runId=detail.runId, logs=detail.logs)


@router.get("/{runtime_id}/events", response_model=RuntimeEventsResponse)
def runtime_events(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, context, db)
    return RuntimeEventsResponse(runId=detail.runId, events=detail.events)


@router.get("/{runtime_id}/events/stream")
async def runtime_event_stream(
    runtime_id: str,
    request: Request,
    afterSequence: int = Query(default=0, ge=0),
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    initial = None
    missing_checks = 0
    while initial is None:
        try:
            initial = _load_runtime_detail(runtime_id, context, db)
            break
        except AppError as exc:
            if exc.code != "RUNTIME_NOT_FOUND":
                raise
            if await request.is_disconnected():
                async def empty_stream():
                    if False:
                        yield ""
                return StreamingResponse(
                    empty_stream(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            missing_checks += 1
            if missing_checks >= 40:
                raise
            await asyncio.sleep(0.25)

    last_event_id = request.headers.get("last-event-id")
    try:
        header_cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        header_cursor = 0
    start_cursor = max(afterSequence, header_cursor)

    async def generate():
        cursor = start_cursor
        snapshot = initial
        last_heartbeat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            live = runtime_tracker.get(runtime_id)
            if live is not None:
                snapshot = live
            pending = [event for event in snapshot.events if event.sequence > cursor]
            for event in pending:
                cursor = event.sequence
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.sequence}\nevent: runtime\ndata: {payload}\n\n"
                last_heartbeat = time.monotonic()
            if snapshot.status in {"completed", "failed"} and live is None:
                return
            if snapshot.status in {"completed", "failed"} and not pending:
                return
            if time.monotonic() - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.35)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{runtime_id}/feature-pipeline", response_model=RuntimeFeaturePipelineResponse)
def runtime_feature_pipeline(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, context, db)
    return RuntimeFeaturePipelineResponse(runId=detail.runId, targets=detail.featurePipeline)


@router.get("/{runtime_id}/optimization", response_model=RuntimeOptimizationResponse)
def runtime_optimization(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, context, db)
    return RuntimeOptimizationResponse(runId=detail.runId, models=detail.optimization)


@router.get("/{runtime_id}/timeline", response_model=RuntimeTimelineResponse)
def runtime_timeline(runtime_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    detail = _load_runtime_detail(runtime_id, context, db)
    return RuntimeTimelineResponse(runId=detail.runId, timeline=detail.timeline)
