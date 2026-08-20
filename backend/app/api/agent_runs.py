from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends
from fastapi import Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, ensure_experiment_manage_access, get_workspace_context, get_workspace_experiment, require_workspace_write_access
from app.core.errors import AppError, as_http_error
from app.db.models import AgentRunRecord, ReportRecord
from app.db.session import get_db
from app.schemas import AgentArtifact, AgentRunDetail, AgentRunEventsResponse, AgentLlmSession, AgentRunRequest, AgentRunResponse
from app.services.agent.context_builder import build_agent_context
from app.services.agent.orchestrator import _load_bundle, agent_orchestrator, list_agent_skills, plan_agent_run
from app.services.agent.stream_broker import agent_stream_broker
from app.services.agent.run_store import create_agent_run, get_agent_run, list_agent_runs, request_cancel, to_agent_history_item, to_agent_run_detail


router = APIRouter(prefix="/api/experiments", tags=["agent-runs"])


def _ensure_run_scope(record: AgentRunRecord, *, experiment_id: str, context: WorkspaceContext) -> None:
    if record.experiment_id != experiment_id or record.workspace_id != context.workspace.id:
        raise AppError("Agent run does not belong to current experiment/workspace.", 403, "AGENT_RUN_FORBIDDEN")


@router.post("/{experiment_id}/agent/runs", response_model=AgentRunResponse)
def create_experiment_agent_run(
    experiment_id: str,
    request: AgentRunRequest,
    context: WorkspaceContext = Depends(require_workspace_write_access),
    db: Session = Depends(get_db),
):
    try:
        experiment = get_workspace_experiment(db, experiment_id, context)
        ensure_experiment_manage_access(experiment, context)
        reports = db.scalars(
            select(ReportRecord)
            .where(ReportRecord.experiment_id == experiment_id, ReportRecord.workspace_id == context.workspace.id)
            .order_by(ReportRecord.created_at.desc())
        ).all()
        llm = request.llm
        if llm is None or not llm.apiKey.strip() or not llm.baseUrl.strip() or not llm.model.strip():
            raise AppError("请先在 API 设置中配置 DeepSeek 后再使用归因 Agent。", 400, "AGENT_LLM_NOT_CONFIGURED")
        snapshot = build_agent_context(record=experiment, request=request, workspace_name=context.workspace.name, reports=reports)
        bundle = _load_bundle(experiment.id)
        plan, estimated_duration, risks = plan_agent_run(request=request, context=snapshot, bundle=bundle)
        available_skills = list_agent_skills()
        run = create_agent_run(
            db,
            experiment_id=experiment.id,
            workspace_id=context.workspace.id,
            created_by_user_id=context.user.id,
            request=request,
            context=snapshot,
            plan=plan,
            available_skills=available_skills,
            risks=risks,
            estimated_duration=estimated_duration,
            llm_session=AgentLlmSession(provider=llm.provider, baseUrl=llm.baseUrl, model=llm.model, stream=llm.stream),
        )
        if request.autoExecute:
            agent_orchestrator.start(run.id)
            status = "running"
        else:
            status = "planned"
        return AgentRunResponse(
            runId=run.id,
            experimentId=experiment.id,
            status=status,
            plan=plan,
            currentMessage="Agent 已生成计划。" if not request.autoExecute else "Agent 已生成计划并开始执行。",
            availableSkills=available_skills,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/agent/runs/{run_id}/stream")
async def stream_experiment_agent_run(
    experiment_id: str,
    run_id: str,
    request: Request,
    afterCursor: int = Query(default=0, ge=0),
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        experiment = get_workspace_experiment(db, experiment_id, context)
        record = get_agent_run(db, run_id)
        if record is None:
            raise AppError("Agent run was not found.", 404, "AGENT_RUN_NOT_FOUND")
        _ensure_run_scope(record, experiment_id=experiment_id, context=context)
    except AppError as exc:
        raise as_http_error(exc) from exc

    last_event_id = request.headers.get("last-event-id")
    try:
        header_cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        header_cursor = 0
    start_cursor = max(afterCursor, header_cursor)

    async def generate():
        cursor = start_cursor
        last_heartbeat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            pending = agent_stream_broker.list_after(run_id, cursor)
            for event in pending:
                cursor = event.cursor
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.cursor}\nevent: agent\ndata: {payload}\n\n"
                last_heartbeat = time.monotonic()
            detail = to_agent_run_detail(record if cursor == start_cursor else get_agent_run(db, run_id) or record)
            if detail.status in {"completed", "failed", "cancelled"} and not pending:
                return
            if time.monotonic() - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.08)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{experiment_id}/agent/runs/{run_id}", response_model=AgentRunDetail)
def get_experiment_agent_run(
    experiment_id: str,
    run_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        get_workspace_experiment(db, experiment_id, context)
        record = get_agent_run(db, run_id)
        if record is None:
            raise AppError("Agent run was not found.", 404, "AGENT_RUN_NOT_FOUND")
        _ensure_run_scope(record, experiment_id=experiment_id, context=context)
        return to_agent_run_detail(record)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/agent/runs/{run_id}/events", response_model=AgentRunEventsResponse)
def get_experiment_agent_run_events(
    experiment_id: str,
    run_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        get_workspace_experiment(db, experiment_id, context)
        record = get_agent_run(db, run_id)
        if record is None:
            raise AppError("Agent run was not found.", 404, "AGENT_RUN_NOT_FOUND")
        _ensure_run_scope(record, experiment_id=experiment_id, context=context)
        detail = to_agent_run_detail(record)
        return AgentRunEventsResponse(runId=run_id, events=detail.events)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/{experiment_id}/agent/runs/{run_id}/cancel")
def cancel_experiment_agent_run(
    experiment_id: str,
    run_id: str,
    context: WorkspaceContext = Depends(require_workspace_write_access),
    db: Session = Depends(get_db),
):
    try:
        experiment = get_workspace_experiment(db, experiment_id, context)
        ensure_experiment_manage_access(experiment, context)
        record = get_agent_run(db, run_id)
        if record is None:
            raise AppError("Agent run was not found.", 404, "AGENT_RUN_NOT_FOUND")
        _ensure_run_scope(record, experiment_id=experiment_id, context=context)
        request_cancel(db, run_id)
        return {"ok": True}
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/agent/history")
def get_experiment_agent_history(
    experiment_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        get_workspace_experiment(db, experiment_id, context)
        runs = list_agent_runs(db, experiment_id=experiment_id, workspace_id=context.workspace.id, limit=30)
        return [to_agent_history_item(run) for run in runs]
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{experiment_id}/agent/artifacts/{artifact_id}", response_model=AgentArtifact)
def get_experiment_agent_artifact(
    experiment_id: str,
    artifact_id: str,
    context: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        get_workspace_experiment(db, experiment_id, context)
        runs = list_agent_runs(db, experiment_id=experiment_id, workspace_id=context.workspace.id, limit=100)
        for run in runs:
            detail = to_agent_run_detail(run)
            for artifact in detail.artifacts:
                if artifact.artifactId == artifact_id:
                    return artifact
        raise AppError("Agent artifact was not found.", 404, "AGENT_ARTIFACT_NOT_FOUND")
    except AppError as exc:
        raise as_http_error(exc) from exc
