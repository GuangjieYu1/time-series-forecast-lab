from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentRunRecord
from app.schemas import (
    AgentArtifact,
    AgentContextSnapshot,
    AgentHistoryItem,
    AgentMessage,
    AgentPlanStep,
    AgentRunDetail,
    AgentRunEvent,
    AgentRunRequest,
    AgentSkillDefinition,
    AgentSkillInvocation,
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def create_agent_run(
    db: Session,
    *,
    experiment_id: str,
    workspace_id: str,
    created_by_user_id: str,
    request: AgentRunRequest,
    context: AgentContextSnapshot,
    plan: list[AgentPlanStep],
    available_skills: list[AgentSkillDefinition],
    risks: list[str],
    estimated_duration: str | None,
) -> AgentRunRecord:
    now = utc_iso()
    record = AgentRunRecord(
        id=f"arun_{uuid.uuid4().hex[:12]}",
        experiment_id=experiment_id,
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        request_json=_dump(request.model_dump(mode="json")),
        context_json=_dump(context.model_dump(mode="json")),
        plan_json=_dump([step.model_dump(mode="json") for step in plan]),
        events_json=_dump(
            [
                AgentRunEvent(
                    eventId=f"evt_{uuid.uuid4().hex[:10]}",
                    type="plan",
                    title="Plan created",
                    detail="Agent 已生成执行计划，准备按顺序调用 skills。",
                    timestamp=now,
                    status="planned",
                ).model_dump(mode="json")
            ]
        ),
        artifacts_json=_dump([]),
        messages_json=_dump([AgentMessage(role="user", content=request.prompt, createdAt=now).model_dump(mode="json")]),
        invocations_json=_dump([]),
        summary_json=_dump(
            {
                "availableSkills": [skill.model_dump(mode="json") for skill in available_skills],
                "risks": risks,
                "estimatedDuration": estimated_duration,
            }
        ),
        status="planned",
        cancel_requested=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_agent_run(db: Session, run_id: str) -> AgentRunRecord | None:
    return db.get(AgentRunRecord, run_id)


def list_agent_runs(db: Session, *, experiment_id: str, workspace_id: str, limit: int = 20) -> list[AgentRunRecord]:
    return (
        db.scalars(
            select(AgentRunRecord)
            .where(AgentRunRecord.experiment_id == experiment_id, AgentRunRecord.workspace_id == workspace_id)
            .order_by(AgentRunRecord.created_at.desc())
            .limit(limit)
        ).all()
    )


def append_event(db: Session, run_id: str, event: AgentRunEvent) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    events = _loads(record.events_json, [])
    events.append(event.model_dump(mode="json"))
    record.events_json = _dump(events)
    db.commit()


def append_message(db: Session, run_id: str, message: AgentMessage) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    messages = _loads(record.messages_json, [])
    messages.append(message.model_dump(mode="json"))
    record.messages_json = _dump(messages)
    db.commit()


def append_artifact(db: Session, run_id: str, artifact: AgentArtifact) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    artifacts = _loads(record.artifacts_json, [])
    artifacts.append(artifact.model_dump(mode="json"))
    record.artifacts_json = _dump(artifacts)
    db.commit()


def upsert_invocation(db: Session, run_id: str, invocation: AgentSkillInvocation) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    invocations = _loads(record.invocations_json, [])
    updated = False
    payload = invocation.model_dump(mode="json")
    for index, row in enumerate(invocations):
        if isinstance(row, dict) and row.get("invocationId") == invocation.invocationId:
            invocations[index] = payload
            updated = True
            break
    if not updated:
        invocations.append(payload)
    record.invocations_json = _dump(invocations)
    db.commit()


def replace_plan(db: Session, run_id: str, plan: list[AgentPlanStep]) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    record.plan_json = _dump([step.model_dump(mode="json") for step in plan])
    db.commit()


def update_run_status(db: Session, run_id: str, status: str, summary: str | None = None) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    record.status = status
    if summary is not None:
        summary_json = _loads(record.summary_json, {})
        summary_json["summary"] = summary
        record.summary_json = _dump(summary_json)
    db.commit()


def request_cancel(db: Session, run_id: str) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    record.cancel_requested = True
    db.commit()


def is_cancel_requested(db: Session, run_id: str) -> bool:
    record = get_agent_run(db, run_id)
    return bool(record.cancel_requested) if record else False


def to_agent_run_detail(record: AgentRunRecord) -> AgentRunDetail:
    summary = _loads(record.summary_json, {})
    messages = [AgentMessage.model_validate(item) for item in _loads(record.messages_json, []) if isinstance(item, dict)]
    assistant_messages = [message.content for message in messages if message.role == "assistant" and message.content]
    return AgentRunDetail(
        runId=record.id,
        experimentId=record.experiment_id,
        workspaceId=record.workspace_id,
        createdByUserId=record.created_by_user_id,
        status=record.status,
        request=AgentRunRequest.model_validate(_loads(record.request_json, {})),
        context=AgentContextSnapshot.model_validate(_loads(record.context_json, {})),
        plan=[AgentPlanStep.model_validate(item) for item in _loads(record.plan_json, []) if isinstance(item, dict)],
        events=[AgentRunEvent.model_validate(item) for item in _loads(record.events_json, []) if isinstance(item, dict)],
        messages=messages,
        skillInvocations=[AgentSkillInvocation.model_validate(item) for item in _loads(record.invocations_json, []) if isinstance(item, dict)],
        artifacts=[AgentArtifact.model_validate(item) for item in _loads(record.artifacts_json, []) if isinstance(item, dict)],
        availableSkills=[AgentSkillDefinition.model_validate(item) for item in summary.get("availableSkills") or [] if isinstance(item, dict)],
        estimatedDuration=summary.get("estimatedDuration"),
        risks=[str(item) for item in summary.get("risks") or [] if item],
        summary=summary.get("summary") or (assistant_messages[-1] if assistant_messages else None),
        canCancel=record.status in {"planned", "running"} and not record.cancel_requested,
        createdAt=record.created_at.astimezone(timezone.utc).isoformat(),
        updatedAt=record.updated_at.astimezone(timezone.utc).isoformat(),
    )


def to_agent_history_item(record: AgentRunRecord) -> AgentHistoryItem:
    detail = to_agent_run_detail(record)
    preview = detail.request.prompt.strip()
    preview = preview[:80] + "…" if len(preview) > 80 else preview
    return AgentHistoryItem(
        runId=detail.runId,
        requestPreview=preview,
        status=detail.status,
        createdAt=detail.createdAt,
        updatedAt=detail.updatedAt,
        artifactCount=len(detail.artifacts),
        skillIds=[step.skillId for step in detail.plan],
        lastAssistantMessage=next((message.content for message in reversed(detail.messages) if message.role == "assistant"), None),
    )
