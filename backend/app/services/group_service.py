from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import utc_now
from app.db.models import (
    UserGroupJoinRequestRecord,
    UserGroupMembershipRecord,
    UserGroupRecord,
    UserRecord,
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from app.services.wecom_notifier import notify_group_join_request


def get_public_workspace(db: Session, group_id: str) -> WorkspaceRecord | None:
    return db.scalar(
        select(WorkspaceRecord).where(WorkspaceRecord.kind == "public", WorkspaceRecord.group_id == group_id)
    )


def create_public_workspace(db: Session, group: UserGroupRecord) -> WorkspaceRecord:
    existing = get_public_workspace(db, group.id)
    if existing is not None:
        return existing
    workspace = WorkspaceRecord(
        id=f"ws_{uuid.uuid4().hex[:12]}",
        name=f"{group.name} · Public",
        kind="public",
        owner_user_id=group.created_by_user_id,
        group_id=group.id,
        is_read_only=group.archived_at is not None,
        created_at=utc_now(),
    )
    db.add(workspace)
    db.flush()
    return workspace


def get_group_membership(db: Session, group_id: str, user_id: str) -> UserGroupMembershipRecord | None:
    return db.scalar(
        select(UserGroupMembershipRecord).where(
            UserGroupMembershipRecord.group_id == group_id,
            UserGroupMembershipRecord.user_id == user_id,
        )
    )


def is_group_manager(db: Session, group_id: str | None, user_id: str) -> bool:
    if not group_id:
        return False
    membership = get_group_membership(db, group_id, user_id)
    return membership is not None and membership.role == "manager"


def can_manage_group(db: Session, group_id: str, user: UserRecord) -> bool:
    return user.is_admin or is_group_manager(db, group_id, user.id)


def grant_group_membership(
    db: Session,
    *,
    group: UserGroupRecord,
    user: UserRecord,
    role: str = "member",
) -> UserGroupMembershipRecord:
    if role not in {"member", "manager"}:
        raise AppError("无效的用户组角色。", 400, "USER_GROUP_ROLE_INVALID")
    if group.archived_at is not None:
        raise AppError("已归档的用户组不能增加成员。", 409, "USER_GROUP_ARCHIVED")
    membership = get_group_membership(db, group.id, user.id)
    now = utc_now()
    if membership is None:
        membership = UserGroupMembershipRecord(
            id=f"ugm_{uuid.uuid4().hex[:12]}",
            group_id=group.id,
            user_id=user.id,
            role=role,
            created_at=now,
        )
        db.add(membership)
    elif role == "manager":
        membership.role = "manager"

    workspace = create_public_workspace(db, group)
    workspace_membership = db.scalar(
        select(WorkspaceMembershipRecord).where(
            WorkspaceMembershipRecord.workspace_id == workspace.id,
            WorkspaceMembershipRecord.user_id == user.id,
        )
    )
    workspace_role = "manager" if membership.role == "manager" else "member"
    if workspace_membership is None:
        db.add(
            WorkspaceMembershipRecord(
                id=f"wm_{uuid.uuid4().hex[:12]}",
                workspace_id=workspace.id,
                user_id=user.id,
                role=workspace_role,
                created_at=now,
            )
        )
    else:
        workspace_membership.role = workspace_role
    db.flush()
    return membership


def remove_group_membership(db: Session, *, group: UserGroupRecord, user: UserRecord) -> None:
    membership = get_group_membership(db, group.id, user.id)
    if membership is None:
        raise AppError("你不在该用户组中。", 404, "USER_GROUP_MEMBERSHIP_NOT_FOUND")
    if membership.role == "manager":
        manager_count = int(
            db.scalar(
                select(func.count())
                .select_from(UserGroupMembershipRecord)
                .where(UserGroupMembershipRecord.group_id == group.id, UserGroupMembershipRecord.role == "manager")
            )
            or 0
        )
        if manager_count <= 1:
            raise AppError("不能移除或退出最后一名组管理员。", 409, "LAST_GROUP_MANAGER")
    workspace = get_public_workspace(db, group.id)
    if workspace is not None:
        workspace_membership = db.scalar(
            select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.workspace_id == workspace.id,
                WorkspaceMembershipRecord.user_id == user.id,
            )
        )
        if workspace_membership is not None:
            db.delete(workspace_membership)
    db.delete(membership)


def set_group_managers(db: Session, *, group: UserGroupRecord, manager_user_ids: list[str]) -> None:
    normalized = list(dict.fromkeys(value.strip() for value in manager_user_ids if value.strip()))
    if not normalized:
        raise AppError("每个用户组至少需要一名组管理员。", 400, "GROUP_MANAGER_REQUIRED")
    managers = db.scalars(select(UserRecord).where(UserRecord.id.in_(normalized), UserRecord.is_active.is_(True))).all()
    if len(managers) != len(normalized):
        raise AppError("组管理员列表中存在无效或已停用用户。", 404, "GROUP_MANAGER_NOT_FOUND")

    current_memberships = db.scalars(
        select(UserGroupMembershipRecord).where(UserGroupMembershipRecord.group_id == group.id)
    ).all()
    workspace = get_public_workspace(db, group.id)
    for membership in current_memberships:
        if membership.role == "manager" and membership.user_id not in normalized:
            membership.role = "member"
            if workspace is not None:
                workspace_membership = db.scalar(
                    select(WorkspaceMembershipRecord).where(
                        WorkspaceMembershipRecord.workspace_id == workspace.id,
                        WorkspaceMembershipRecord.user_id == membership.user_id,
                    )
                )
                if workspace_membership is not None:
                    workspace_membership.role = "member"
    for user in managers:
        grant_group_membership(db, group=group, user=user, role="manager")
    db.flush()


def create_group_join_requests(
    db: Session,
    *,
    user: UserRecord,
    group_ids: list[str],
) -> list[UserGroupJoinRequestRecord]:
    normalized = list(dict.fromkeys(value.strip() for value in group_ids if value.strip()))
    groups = db.scalars(select(UserGroupRecord).where(UserGroupRecord.id.in_(normalized))).all() if normalized else []
    groups_by_id = {group.id: group for group in groups}
    if len(groups_by_id) != len(normalized):
        raise AppError("申请列表中存在无效用户组。", 404, "USER_GROUP_NOT_FOUND")
    requests: list[UserGroupJoinRequestRecord] = []
    for group_id in normalized:
        group = groups_by_id[group_id]
        if group.archived_at is not None:
            raise AppError(f"用户组「{group.name}」已归档。", 409, "USER_GROUP_ARCHIVED")
        if get_group_membership(db, group_id, user.id) is not None:
            continue
        pending = db.scalar(
            select(UserGroupJoinRequestRecord).where(
                UserGroupJoinRequestRecord.group_id == group_id,
                UserGroupJoinRequestRecord.user_id == user.id,
                UserGroupJoinRequestRecord.status == "pending",
            )
        )
        if pending is not None:
            continue
        request = UserGroupJoinRequestRecord(
            id=f"ugr_{uuid.uuid4().hex[:12]}",
            group_id=group_id,
            user_id=user.id,
            status="pending",
            notify_status="pending",
            created_at=utc_now(),
        )
        db.add(request)
        requests.append(request)
    db.flush()
    return requests


def notify_group_join_requests(db: Session, requests: list[UserGroupJoinRequestRecord]) -> None:
    settings = get_settings()
    for request in requests:
        group = db.get(UserGroupRecord, request.group_id)
        user = db.get(UserRecord, request.user_id)
        if group is None or user is None:
            request.notify_status = "failed"
            request.notify_error = "用户或用户组不存在。"
            continue
        try:
            result = notify_group_join_request(
                request_id=request.id,
                group_name=group.name,
                username=user.username,
                display_name=user.display_name,
                settings=settings,
            )
        except Exception as exc:  # Notification must never invalidate an already-created join request.
            request.notify_status = "failed"
            request.notify_error = f"企业微信通知发送失败：{exc}"
        else:
            request.notify_status = result.status
            request.notify_error = result.error
    db.flush()
