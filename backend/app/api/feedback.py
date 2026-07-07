from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, as_http_error
from app.db.models import FeedbackRecord
from app.db.session import get_db
from app.schemas import (
    FeedbackCreateRequest,
    FeedbackItem,
    FeedbackListResponse,
    FeedbackNotifyTestRequest,
    FeedbackNotifyTestResponse,
    FeedbackStatusUpdateRequest,
)
from app.services.wecom_notifier import notify_feedback, notify_test_message


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_item(record: FeedbackRecord) -> FeedbackItem:
    return FeedbackItem(
        feedbackId=record.id,
        kind=record.kind,
        title=record.title,
        content=record.content,
        sourcePage=record.source_page,
        status=record.status,
        notifyStatus=record.notify_status,
        notifyError=record.notify_error,
        createdAt=record.created_at.isoformat(),
        updatedAt=record.updated_at.isoformat(),
    )


@router.post("", response_model=FeedbackItem)
def create_feedback(
    payload: FeedbackCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        content = payload.content.strip()
        if not content:
            raise AppError("反馈内容不能为空。", 422, "VALIDATION_ERROR")
        record = FeedbackRecord(
            id=f"fb_{uuid4().hex[:16]}",
            kind=payload.kind,
            title=payload.title.strip() if payload.title else None,
            content=content,
            source_page=payload.sourcePage,
            user_agent=request.headers.get("user-agent"),
            status="open",
            notify_status="pending",
            notify_error=None,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        result = notify_feedback(record, settings)
        record.notify_status = result.status
        record.notify_error = result.error
        record.updated_at = _now()
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_item(record)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    statement = select(FeedbackRecord).order_by(FeedbackRecord.created_at.desc()).limit(limit)
    if status:
        statement = select(FeedbackRecord).where(FeedbackRecord.status == status).order_by(FeedbackRecord.created_at.desc()).limit(limit)
    records = db.scalars(statement).all()
    return FeedbackListResponse(items=[_to_item(record) for record in records])


@router.patch("/{feedback_id}/status", response_model=FeedbackItem)
def update_feedback_status(feedback_id: str, payload: FeedbackStatusUpdateRequest, db: Session = Depends(get_db)):
    try:
        record = db.get(FeedbackRecord, feedback_id)
        if record is None:
            raise AppError("反馈记录不存在。", 404, "FEEDBACK_NOT_FOUND")
        record.status = payload.status
        record.updated_at = _now()
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_item(record)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/test-wecom", response_model=FeedbackNotifyTestResponse)
def test_wecom_notification(payload: FeedbackNotifyTestRequest, settings: Settings = Depends(get_settings)):
    result = notify_test_message(payload.message, settings)
    if result.status == "sent":
        return FeedbackNotifyTestResponse(success=True, notifyStatus="sent", message="企业微信测试通知已发送。")
    if result.status == "skipped":
        return FeedbackNotifyTestResponse(success=False, notifyStatus="skipped", message="未配置企业微信机器人 webhook。", error=result.error)
    return FeedbackNotifyTestResponse(success=False, notifyStatus="failed", message="企业微信测试通知发送失败。", error=result.error)
