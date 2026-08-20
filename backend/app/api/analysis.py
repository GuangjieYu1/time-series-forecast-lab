from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, get_workspace_context, require_workspace_write_access
from app.core.errors import AppError, as_http_error
from app.core.storage import assert_upload_ownership, read_upload_metadata
from app.db.session import get_db
from app.schemas import (
    AnalysisAgentRequest,
    AnalysisAgentResponse,
    AnalysisProfileRequest,
    AnalysisRouteSuggestionRequest,
    DatasetProfile,
    DatasetTransformExecutionRequest,
    DatasetTransformPlan,
    DatasetTransformPlanRequest,
    DatasetTransformResult,
    RouteSuggestion,
    WorkflowRunDetail,
    WorkflowStageDetail,
    WorkflowStartRequest,
)
from app.services.analysis_platform import (
    analyze_dataset_with_agent,
    build_dataset_profile,
    execute_transform,
    plan_transform,
    start_analysis_workflow,
    suggest_routes,
)


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@dataclass
class AnalysisRunSnapshot:
    detail: WorkflowRunDetail
    events: list[dict[str, Any]] = field(default_factory=list)
    stage_durations: list[float] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancelled: bool = False
    cancelled_at: datetime | None = None


_ANALYSIS_RUNS: dict[str, AnalysisRunSnapshot] = {}


def _assert_upload_scope(upload_id: str, context: WorkspaceContext) -> None:
    metadata = read_upload_metadata(upload_id)
    assert_upload_ownership(metadata, user_id=context.user.id, workspace_id=context.workspace.id)


def _stage_durations_for(analysis_type: str, stage_count: int) -> list[float]:
    templates = {
        "attribution": [1.0, 1.4, 1.2, 0.8],
        "supervised_ml": [1.1, 1.6, 1.8, 1.1, 0.9],
        "clustering": [1.0, 1.4, 1.7, 1.0, 0.8],
        "forecast": [0.6],
    }
    durations = templates.get(analysis_type, [1.0] * max(stage_count, 1))
    if len(durations) >= stage_count:
        return durations[:stage_count]
    return durations + [1.0] * (stage_count - len(durations))


def _elapsed_seconds(snapshot: AnalysisRunSnapshot) -> float:
    end_time = snapshot.cancelled_at or datetime.now(timezone.utc)
    return max((end_time - snapshot.started_at).total_seconds(), 0.0)


def _materialize_detail(snapshot: AnalysisRunSnapshot) -> WorkflowRunDetail:
    detail = snapshot.detail.model_copy(deep=True)
    if not detail.stages:
        return detail

    if snapshot.cancelled:
        detail.status = "failed"
        detail.currentStage = None
        detail.completedAt = (snapshot.cancelled_at or datetime.now(timezone.utc)).isoformat()
        detail.progressPercent = max(detail.progressPercent, 0)
        detail.stages = [
            WorkflowStageDetail(
                stageId=stage.stageId,
                title=stage.title,
                description=stage.description,
                status="failed" if index == 0 else stage.status,
                progressPercent=0 if index == 0 else stage.progressPercent,
            )
            for index, stage in enumerate(detail.stages)
        ]
        return detail

    elapsed = _elapsed_seconds(snapshot)
    total = max(sum(snapshot.stage_durations), 0.1)
    cumulative = 0.0
    rendered_stages: list[WorkflowStageDetail] = []
    current_stage_id: str | None = None
    completed_at: str | None = None

    for index, stage in enumerate(detail.stages):
        duration = snapshot.stage_durations[index] if index < len(snapshot.stage_durations) else 1.0
        stage_start = cumulative
        stage_end = cumulative + duration
        cumulative = stage_end
        if elapsed >= stage_end:
            rendered_stages.append(
                WorkflowStageDetail(
                    stageId=stage.stageId,
                    title=stage.title,
                    description=stage.description,
                    status="completed",
                    progressPercent=100,
                )
            )
            continue
        if elapsed >= stage_start:
            current_stage_id = stage.stageId
            stage_progress = int(round(((elapsed - stage_start) / max(duration, 0.1)) * 100))
            rendered_stages.append(
                WorkflowStageDetail(
                    stageId=stage.stageId,
                    title=stage.title,
                    description=stage.description,
                    status="running",
                    progressPercent=max(5, min(stage_progress, 99)),
                )
            )
            for tail in detail.stages[index + 1 :]:
                rendered_stages.append(
                    WorkflowStageDetail(
                        stageId=tail.stageId,
                        title=tail.title,
                        description=tail.description,
                        status="planned",
                        progressPercent=0,
                    )
                )
            break
        rendered_stages.append(
            WorkflowStageDetail(
                stageId=stage.stageId,
                title=stage.title,
                description=stage.description,
                status="planned",
                progressPercent=0,
            )
        )
    else:
        current_stage_id = detail.stages[-1].stageId if detail.stages else None

    progress = int(round(min(elapsed / total, 1.0) * 100))
    if elapsed >= total:
        detail.status = "completed"
        detail.progressPercent = 100
        detail.currentStage = detail.stages[-1].stageId if detail.stages else current_stage_id
        completed_at = (snapshot.started_at.timestamp() + total)
        detail.completedAt = datetime.fromtimestamp(completed_at, tz=timezone.utc).isoformat()
        rendered_stages = [
            WorkflowStageDetail(
                stageId=stage.stageId,
                title=stage.title,
                description=stage.description,
                status="completed",
                progressPercent=100,
            )
            for stage in detail.stages
        ]
    else:
        detail.status = "running"
        detail.progressPercent = max(3, progress)
        detail.currentStage = current_stage_id
        detail.completedAt = None

    detail.stages = rendered_stages
    return detail


def _materialize_events(snapshot: AnalysisRunSnapshot) -> list[dict[str, Any]]:
    if snapshot.cancelled:
        return [{key: value for key, value in event.items() if key != "availableAfterSeconds"} for event in snapshot.events]
    elapsed = _elapsed_seconds(snapshot)
    visible_events: list[dict[str, Any]] = []
    for event in snapshot.events:
        available_after = float(event.get("availableAfterSeconds", 0))
        if elapsed >= available_after:
            visible_events.append({key: value for key, value in event.items() if key != "availableAfterSeconds"})
    return visible_events


@router.post("/profile", response_model=DatasetProfile)
def analysis_profile(request: AnalysisProfileRequest, context: WorkspaceContext = Depends(get_workspace_context)):
    try:
        _assert_upload_scope(request.uploadId, context)
        return build_dataset_profile(request.uploadId, request.sheetName, workspace_id=context.workspace.id)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/routes/suggest", response_model=RouteSuggestion)
def analysis_route_suggest(request: AnalysisRouteSuggestionRequest, context: WorkspaceContext = Depends(get_workspace_context)):
    try:
        _assert_upload_scope(request.uploadId, context)
        profile = build_dataset_profile(request.uploadId, request.sheetName, workspace_id=context.workspace.id)
        return suggest_routes(profile)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/agent/analyze", response_model=AnalysisAgentResponse)
def analysis_agent_analyze(request: AnalysisAgentRequest, context: WorkspaceContext = Depends(get_workspace_context)):
    try:
        _assert_upload_scope(request.uploadId, context)
        return analyze_dataset_with_agent(
            upload_id=request.uploadId,
            sheet_name=request.sheetName,
            prompt=request.prompt,
            current_page=request.currentPage,
            selected_route=request.selectedRoute,
            workspace_id=context.workspace.id,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/transforms/plan", response_model=DatasetTransformPlan)
def analysis_transform_plan(request: DatasetTransformPlanRequest, context: WorkspaceContext = Depends(get_workspace_context)):
    try:
        _assert_upload_scope(request.uploadId, context)
        return plan_transform(
            request.uploadId,
            request.sheetName,
            request.transformType,
            request.columns,
            workspace_id=context.workspace.id,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/transforms/execute", response_model=DatasetTransformResult)
def analysis_transform_execute(request: DatasetTransformExecutionRequest, context: WorkspaceContext = Depends(require_workspace_write_access)):
    try:
        if not request.confirmed:
            raise AppError("当前变换需要用户确认后才能执行。", 400, "TRANSFORM_CONFIRMATION_REQUIRED")
        _assert_upload_scope(request.uploadId, context)
        return execute_transform(
            request.uploadId,
            request.sheetName,
            request.transformType,
            request.columns,
            user_id=context.user.id,
            workspace_id=context.workspace.id,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


def _start_workflow(analysis_type: str, request: WorkflowStartRequest, context: WorkspaceContext, db: Session) -> WorkflowRunDetail:
    _assert_upload_scope(request.uploadId, context)
    detail = start_analysis_workflow(
        analysis_type,
        upload_id=request.uploadId,
        sheet_name=request.sheetName,
        experiment_name=request.experimentName,
        target_column=request.targetColumn,
        time_column=request.timeColumn,
        grouping_columns=request.groupingColumns,
        feature_columns=request.featureColumns,
        cluster_count=request.clusterCount,
        workspace_id=context.workspace.id,
        created_by_user_id=context.user.id,
        db=db,
    )
    stage_durations = _stage_durations_for(analysis_type, len(detail.stages))
    cumulative = 0.0
    events: list[dict[str, Any]] = []
    for index, stage in enumerate(detail.stages):
        cumulative += stage_durations[index] if index < len(stage_durations) else 1.0
        events.append(
            {
                "eventId": f"{detail.runId}_evt_{index + 1}",
                "type": "stage",
                "title": stage.title,
                "detail": stage.description,
                "status": "completed",
                "availableAfterSeconds": cumulative,
            }
        )
    events.append(
        {
            "eventId": f"{detail.runId}_evt_terminal",
            "type": "terminal",
            "title": "Workflow completed",
            "detail": detail.summary,
            "status": "completed",
            "availableAfterSeconds": max(cumulative, 0.1),
        }
    )
    _ANALYSIS_RUNS[detail.runId] = AnalysisRunSnapshot(
        detail=detail,
        events=events,
        stage_durations=stage_durations,
    )
    return detail


@router.post("/workflows/forecast/start", response_model=WorkflowRunDetail)
def start_forecast_workflow(request: WorkflowStartRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        return _start_workflow("forecast", request, context, db)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/workflows/attribution/start", response_model=WorkflowRunDetail)
def start_attribution_workflow(request: WorkflowStartRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        return _start_workflow("attribution", request, context, db)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/workflows/supervised-ml/start", response_model=WorkflowRunDetail)
def start_supervised_workflow(request: WorkflowStartRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        return _start_workflow("supervised_ml", request, context, db)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/workflows/clustering/start", response_model=WorkflowRunDetail)
def start_clustering_workflow(request: WorkflowStartRequest, context: WorkspaceContext = Depends(require_workspace_write_access), db: Session = Depends(get_db)):
    try:
        return _start_workflow("clustering", request, context, db)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/runs/{run_id}", response_model=WorkflowRunDetail)
def get_analysis_run(run_id: str, context: WorkspaceContext = Depends(get_workspace_context)):
    snapshot = _ANALYSIS_RUNS.get(run_id)
    if snapshot is None:
        raise as_http_error(AppError("Analysis run was not found.", 404, "ANALYSIS_RUN_NOT_FOUND"))
    return _materialize_detail(snapshot)


@router.get("/runs/{run_id}/events")
def get_analysis_run_events(run_id: str, context: WorkspaceContext = Depends(get_workspace_context)):
    snapshot = _ANALYSIS_RUNS.get(run_id)
    if snapshot is None:
        raise as_http_error(AppError("Analysis run was not found.", 404, "ANALYSIS_RUN_NOT_FOUND"))
    return {"runId": run_id, "events": _materialize_events(snapshot)}


@router.post("/runs/{run_id}/cancel")
def cancel_analysis_run(run_id: str, context: WorkspaceContext = Depends(require_workspace_write_access)):
    snapshot = _ANALYSIS_RUNS.get(run_id)
    if snapshot is None:
        raise as_http_error(AppError("Analysis run was not found.", 404, "ANALYSIS_RUN_NOT_FOUND"))
    snapshot.cancelled = True
    snapshot.cancelled_at = datetime.now(timezone.utc)
    snapshot.detail.status = "failed"
    snapshot.detail.warnings.append("用户已取消当前 analysis run。")
    snapshot.events.append(
        {
            "eventId": f"{run_id}_evt_cancel",
            "type": "cancelled",
            "title": "Workflow cancelled",
            "detail": "用户已取消当前 run。",
            "status": "failed",
            "availableAfterSeconds": _elapsed_seconds(snapshot),
        }
    )
    return {"ok": True}
