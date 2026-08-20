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
from app.schemas import AddWorkspaceMemberRequest, CreateWorkspaceRequest, ReplaceWorkspaceMembersRequest, WorkspaceMemberResponse, WorkspaceSummary, UpdateWorkspaceRequest
from app.services.auth_service import delete_workspace_and_contents, list_workspace_summaries


router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(current_user: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    return list_workspace_summaries(db, current_user)


@router.post("", response_model=WorkspaceSummary)
def create_workspace(payload: CreateWorkspaceRequest, current_user: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    try:
        member_ids = list(dict.fromkeys(user_id.strip() for user_id in payload.memberUserIds if user_id.strip() and user_id.strip() != current_user.id))
        members = db.scalars(select(UserRecord).where(UserRecord.id.in_(member_ids), UserRecord.is_active.is_(True))).all() if member_ids else []
        if len(members) != len(member_ids):
            raise AppError("协作成员中存在无效或已停用用户。", 404, "WORKSPACE_MEMBER_NOT_FOUND")
        workspace = WorkspaceRecord(
            id=f"ws_{uuid.uuid4().hex[:12]}",
            name=payload.name.strip(),
            kind="custom",
            owner_user_id=current_user.id,
            group_id=None,
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
        for user in members:
            db.add(
                WorkspaceMembershipRecord(
                    id=f"wm_{uuid.uuid4().hex[:12]}",
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="member",
                    created_at=utc_now(),
                )
            )
        db.commit()
        return WorkspaceSummary(
            workspaceId=workspace.id,
            name=workspace.name,
            kind="custom",
            role="owner",
            isReadOnly=workspace.is_read_only,
            ownerUserId=workspace.owner_user_id,
            groupId=None,
            isPersonal=False,
            isOwner=True,
            isArchived=False,
            canWrite=True,
            canManageMembers=True,
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
            groupId=context.workspace.group_id,
            isPersonal=False,
            isOwner=True,
            isArchived=False,
            canWrite=True,
            canManageMembers=True,
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


@router.put("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def replace_members(
    workspace_id: str,
    payload: ReplaceWorkspaceMembersRequest,
    context: WorkspaceContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    try:
        if context.workspace.id != workspace_id:
            raise AppError("当前工作区不匹配。", 403, "WORKSPACE_OWNER_REQUIRED")
        requested_ids = list(
            dict.fromkeys(
                user_id.strip()
                for user_id in payload.memberUserIds
                if user_id.strip() and user_id.strip() != context.workspace.owner_user_id
            )
        )
        users = db.scalars(select(UserRecord).where(UserRecord.id.in_(requested_ids), UserRecord.is_active.is_(True))).all() if requested_ids else []
        if len(users) != len(requested_ids):
            raise AppError("协作成员中存在无效或已停用用户。", 404, "WORKSPACE_MEMBER_NOT_FOUND")
        current = db.scalars(
            select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.workspace_id == workspace_id,
                WorkspaceMembershipRecord.role == "member",
            )
        ).all()
        requested_set = set(requested_ids)
        current_by_user = {membership.user_id: membership for membership in current}
        for membership in current:
            if membership.user_id not in requested_set:
                db.delete(membership)
        now = utc_now()
        for user in users:
            if user.id not in current_by_user:
                db.add(
                    WorkspaceMembershipRecord(
                        id=f"wm_{uuid.uuid4().hex[:12]}",
                        workspace_id=workspace_id,
                        user_id=user.id,
                        role="member",
                        created_at=now,
                    )
                )
        db.commit()
        return list_members(workspace_id, context, db)
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
