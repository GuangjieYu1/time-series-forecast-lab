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
    AgentConversationItem,
    AgentContextSnapshot,
    AgentHistoryItem,
    AgentLlmSession,
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


def _normalize_plan_step_payload(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    description = normalized.get("description")
    if not isinstance(description, str) or not description.strip():
        legacy_detail = normalized.get("detail")
        if isinstance(legacy_detail, str):
            normalized["description"] = legacy_detail

    runs = normalized.get("runs")
    if not isinstance(runs, list):
        runs = []
    if normalized.get("runsModel"):
        runs = [*runs, "model-run"]
    normalized["runs"] = runs

    generates = normalized.get("generates")
    if not isinstance(generates, list):
        generates = []
    if normalized.get("generatesChart"):
        generates = [*generates, "chart"]
    if normalized.get("writesReport"):
        generates = [*generates, "report"]
    normalized["generates"] = list(dict.fromkeys(str(item) for item in generates if item))

    side_effects = normalized.get("sideEffects")
    normalized["sideEffects"] = side_effects if isinstance(side_effects, list) else []
    warnings = normalized.get("warnings")
    if not isinstance(warnings, list):
        normalized["warnings"] = []
    return normalized


def _normalize_invocation_payload(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    warnings = normalized.get("warnings")
    if isinstance(warnings, list):
        normalized["warnings"] = [str(item) for item in warnings if item]
    else:
        warning = normalized.get("warning")
        normalized["warnings"] = [str(warning)] if warning else []
    artifact_ids = normalized.get("artifactIds")
    normalized["artifactIds"] = [str(item) for item in artifact_ids] if isinstance(artifact_ids, list) else []
    return normalized


def _normalize_artifact_payload(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    data = normalized.get("data")
    if not isinstance(data, dict):
        legacy_payload = normalized.get("payload")
        normalized["data"] = legacy_payload if isinstance(legacy_payload, dict) else {}
    markdown = normalized.get("markdown")
    if markdown is None:
        payload = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
        markdown = payload.get("contentMarkdown") or payload.get("content")
        normalized["markdown"] = markdown if isinstance(markdown, str) else None
    if "reportCompatible" not in normalized and "linksToReport" in normalized:
        normalized["reportCompatible"] = bool(normalized.get("linksToReport"))
    if "downloadable" not in normalized:
        normalized["downloadable"] = False
    return normalized


def _normalize_conversation_payload(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    title = normalized.get("title")
    if title is not None and not isinstance(title, str):
        normalized["title"] = str(title)
    content = normalized.get("contentMarkdown")
    if not isinstance(content, str):
        legacy_content = normalized.get("content")
        normalized["contentMarkdown"] = str(legacy_content or "")
    if not normalized.get("createdAt"):
        normalized["createdAt"] = utc_iso()
    if normalized.get("streamState") not in {"streaming", "final"}:
        normalized["streamState"] = "final"
    return normalized


def _legacy_conversation(
    *,
    request: AgentRunRequest,
    messages: list[AgentMessage],
    plan: list[AgentPlanStep],
    artifacts: list[AgentArtifact],
) -> list[AgentConversationItem]:
    items: list[AgentConversationItem] = [
        AgentConversationItem(
            itemId=f"conv_user_{index}",
            kind="user" if message.role == "user" else "assistant",
            title="用户问题" if message.role == "user" else "Agent 回复",
            contentMarkdown=message.content,
            createdAt=message.createdAt,
            streamState="final",
        )
        for index, message in enumerate(messages)
    ]
    if not items:
        items.append(
            AgentConversationItem(
                itemId="conv_user_0",
                kind="user",
                title="用户问题",
                contentMarkdown=request.prompt,
                createdAt=utc_iso(),
                streamState="final",
            )
        )
    if plan:
        first_step = plan[0]
        items.append(
            AgentConversationItem(
                itemId="conv_plan_legacy",
                kind="plan",
                title="执行计划",
                contentMarkdown=f"已生成 {len(plan)} 步计划，首步是“{first_step.title}”。",
                stepId=first_step.stepId,
                skillId=first_step.skillId,
                createdAt=items[-1].createdAt,
                streamState="final",
            )
        )
    for artifact in artifacts:
        items.append(
            AgentConversationItem(
                itemId=f"conv_artifact_{artifact.artifactId}",
                kind="artifact",
                title=artifact.title,
                contentMarkdown=artifact.summary,
                artifactId=artifact.artifactId,
                skillId=artifact.sourceSkillId,
                createdAt=artifact.createdAt,
                streamState="final",
            )
        )
    items.sort(key=lambda item: item.createdAt)
    return items


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
    llm_session: AgentLlmSession | None = None,
) -> AgentRunRecord:
    now = utc_iso()
    user_conversation = AgentConversationItem(
        itemId=f"conv_{uuid.uuid4().hex[:10]}",
        kind="user",
        title="用户问题",
        contentMarkdown=request.prompt,
        createdAt=now,
        streamState="final",
    )
    plan_conversation = AgentConversationItem(
        itemId=f"conv_{uuid.uuid4().hex[:10]}",
        kind="plan",
        title="计划已生成",
        contentMarkdown="Agent 已生成执行计划，准备按顺序读取证据并输出分步摘要。",
        createdAt=now,
        streamState="final",
    )
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
        conversation_json=_dump([user_conversation.model_dump(mode="json"), plan_conversation.model_dump(mode="json")]),
        invocations_json=_dump([]),
        summary_json=_dump(
            {
                "availableSkills": [skill.model_dump(mode="json") for skill in available_skills],
                "risks": risks,
                "estimatedDuration": estimated_duration,
            }
        ),
        llm_session_json=_dump(llm_session.model_dump(mode="json")) if llm_session else None,
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


def append_conversation_item(db: Session, run_id: str, item: AgentConversationItem) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    conversation = _loads(record.conversation_json, [])
    conversation.append(item.model_dump(mode="json"))
    record.conversation_json = _dump(conversation)
    db.commit()


def upsert_conversation_item(db: Session, run_id: str, item: AgentConversationItem) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    conversation = _loads(record.conversation_json, [])
    payload = item.model_dump(mode="json")
    updated = False
    for index, row in enumerate(conversation):
        if isinstance(row, dict) and row.get("itemId") == item.itemId:
            conversation[index] = payload
            updated = True
            break
    if not updated:
        conversation.append(payload)
    record.conversation_json = _dump(conversation)
    db.commit()


def set_llm_session(db: Session, run_id: str, llm_session: AgentLlmSession | None) -> None:
    record = get_agent_run(db, run_id)
    if record is None:
        return
    record.llm_session_json = _dump(llm_session.model_dump(mode="json")) if llm_session else None
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
    plan = [AgentPlanStep.model_validate(_normalize_plan_step_payload(item)) for item in _loads(record.plan_json, []) if isinstance(item, dict)]
    artifacts = [AgentArtifact.model_validate(_normalize_artifact_payload(item)) for item in _loads(record.artifacts_json, []) if isinstance(item, dict)]
    request = AgentRunRequest.model_validate(_loads(record.request_json, {}))
    conversation_rows = [item for item in _loads(record.conversation_json, []) if isinstance(item, dict)]
    conversation = [AgentConversationItem.model_validate(_normalize_conversation_payload(item)) for item in conversation_rows]
    if not conversation:
        conversation = _legacy_conversation(request=request, messages=messages, plan=plan, artifacts=artifacts)
    assistant_messages = [message.content for message in messages if message.role == "assistant" and message.content]
    return AgentRunDetail(
        runId=record.id,
        experimentId=record.experiment_id,
        workspaceId=record.workspace_id,
        createdByUserId=record.created_by_user_id,
        status=record.status,
        request=request,
        context=AgentContextSnapshot.model_validate(_loads(record.context_json, {})),
        plan=plan,
        events=[AgentRunEvent.model_validate(item) for item in _loads(record.events_json, []) if isinstance(item, dict)],
        messages=messages,
        conversation=conversation,
        skillInvocations=[AgentSkillInvocation.model_validate(_normalize_invocation_payload(item)) for item in _loads(record.invocations_json, []) if isinstance(item, dict)],
        artifacts=artifacts,
        availableSkills=[AgentSkillDefinition.model_validate(item) for item in summary.get("availableSkills") or [] if isinstance(item, dict)],
        estimatedDuration=summary.get("estimatedDuration"),
        risks=[str(item) for item in summary.get("risks") or [] if item],
        summary=summary.get("summary") or (assistant_messages[-1] if assistant_messages else None),
        llmSession=AgentLlmSession.model_validate(_loads(record.llm_session_json, {})) if record.llm_session_json else None,
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
