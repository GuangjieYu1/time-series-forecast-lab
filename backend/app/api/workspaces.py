from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, get_workspace_context, require_current_user, require_workspace_owner
from app.core.errors import AppError, as_http_error
from app.core.security import utc_now
from app.db.models import UserRecord, WorkspaceMembershipRecord, WorkspaceRecord
from app.db.session import get_db
from app.schemas import AddWorkspaceMemberRequest, CreateWorkspaceRequest, WorkspaceMemberResponse, WorkspaceSummary, UpdateWorkspaceRequest
from app.services.auth_service import delete_workspace_and_contents, list_workspace_summaries


router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(current_user: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    return list_workspace_summaries(db, current_user)


@router.post("", response_model=WorkspaceSummary)
def create_workspace(payload: CreateWorkspaceRequest, current_user: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    try:
        workspace = WorkspaceRecord(
            id=f"ws_{uuid.uuid4().hex[:12]}",
            name=payload.name.strip(),
            kind="shared",
            owner_user_id=current_user.id,
            is_read_only=False,
            created_at=utc_now(),
        )
        db.add(workspace)
        db.flush()
        membership = WorkspaceMembershipRecord(
            id=f"wm_{uuid.uuid4().hex[:12]}",
            workspace_id=workspace.id,
            user_id=current_user.id,
            role="owner",
            created_at=utc_now(),
        )
        db.add(membership)
        db.commit()
        return WorkspaceSummary(
            workspaceId=workspace.id,
            name=workspace.name,
            kind="shared",
            role="owner",
            isReadOnly=workspace.is_read_only,
            ownerUserId=workspace.owner_user_id,
            isPersonal=False,
            isOwner=True,
            createdAt=workspace.created_at.isoformat(),
        )
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceSummary)
def update_workspace(
    workspace_id: str,
    payload: UpdateWorkspaceRequest,
    context: WorkspaceContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("只能修改当前选中的共享工作区。", 403, "WORKSPACE_OWNER_REQUIRED")
        context.workspace.name = payload.name.strip()
        db.commit()
        return WorkspaceSummary(
            workspaceId=context.workspace.id,
            name=context.workspace.name,
            kind=context.workspace.kind,
            role=context.role,
            isReadOnly=context.workspace.is_read_only,
            ownerUserId=context.workspace.owner_user_id,
            isPersonal=False,
            isOwner=True,
            createdAt=context.workspace.created_at.isoformat(),
        )
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, context: WorkspaceContext = Depends(require_workspace_owner), db: Session = Depends(get_db)):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("只能删除当前选中的共享工作区。", 403, "WORKSPACE_OWNER_REQUIRED")
        delete_workspace_and_contents(db, context.workspace)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_members(workspace_id: str, context: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("当前工作区不匹配。", 403, "WORKSPACE_FORBIDDEN")
        rows = db.execute(
            select(WorkspaceMembershipRecord, UserRecord)
            .join(UserRecord, UserRecord.id == WorkspaceMembershipRecord.user_id)
            .where(WorkspaceMembershipRecord.workspace_id == workspace_id)
            .order_by(WorkspaceMembershipRecord.created_at.asc())
        ).all()
        return [
            WorkspaceMemberResponse(
                userId=user.id,
                username=user.username,
                displayName=user.display_name,
                role=membership.role,
                isActive=user.is_active,
                createdAt=membership.created_at.isoformat(),
            )
            for membership, user in rows
        ]
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberResponse)
def add_member(
    workspace_id: str,
    payload: AddWorkspaceMemberRequest,
    context: WorkspaceContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("当前工作区不匹配。", 403, "WORKSPACE_OWNER_REQUIRED")
        if payload.userId == context.workspace.owner_user_id:
            raise AppError("owner 已经在工作区内。", 409, "WORKSPACE_MEMBER_EXISTS")
        user = db.get(UserRecord, payload.userId)
        if user is None:
            raise AppError("用户不存在。", 404, "USER_NOT_FOUND")
        exists = db.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipRecord)
            .where(WorkspaceMembershipRecord.workspace_id == workspace_id, WorkspaceMembershipRecord.user_id == payload.userId)
        )
        if exists:
            raise AppError("该用户已经在工作区中。", 409, "WORKSPACE_MEMBER_EXISTS")
        membership = WorkspaceMembershipRecord(
            id=f"wm_{uuid.uuid4().hex[:12]}",
            workspace_id=workspace_id,
            user_id=payload.userId,
            role="member",
            created_at=utc_now(),
        )
        db.add(membership)
        db.commit()
        return WorkspaceMemberResponse(
            userId=user.id,
            username=user.username,
            displayName=user.display_name,
            role="member",
            isActive=user.is_active,
            createdAt=membership.created_at.isoformat(),
        )
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/{workspace_id}/members/{user_id}")
def remove_member(
    workspace_id: str,
    user_id: str,
    context: WorkspaceContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("当前工作区不匹配。", 403, "WORKSPACE_OWNER_REQUIRED")
        if user_id == context.workspace.owner_user_id:
            raise AppError("不能移除工作区 owner。", 400, "WORKSPACE_OWNER_REMOVE_FORBIDDEN")
        membership = db.scalar(
            select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.workspace_id == workspace_id,
                WorkspaceMembershipRecord.user_id == user_id,
            )
        )
        if membership is None:
            raise AppError("成员不存在。", 404, "WORKSPACE_MEMBER_NOT_FOUND")
        db.delete(membership)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc
