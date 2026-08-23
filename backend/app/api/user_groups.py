from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_current_user
from app.core.errors import AppError, as_http_error
from app.core.security import utc_now
from app.db.models import (
    UserGroupJoinRequestRecord,
    UserGroupMembershipRecord,
    UserGroupRecord,
    UserRecord,
    WorkspaceRecord,
)
from app.db.session import get_db
from app.schemas import (
    CreateGroupJoinRequestsRequest,
    CreateUserGroupRequest,
    GroupJoinRequestSummary,
    GroupMembershipSummary,
    MyGroupStateResponse,
    RegistrationGroupSummary,
    ReviewGroupJoinRequest,
    UpdateUserGroupRequest,
    UserGroupSummary,
    WorkspaceMemberResponse,
)
from app.services.group_service import (
    can_manage_group,
    create_group_join_requests,
    create_public_workspace,
    get_public_workspace,
    grant_group_membership,
    notify_group_join_requests,
    remove_group_membership,
    set_group_managers,
)


router = APIRouter(prefix="/api/user-groups", tags=["user-groups"])


def _serialize_group(db: Session, group: UserGroupRecord) -> UserGroupSummary:
    member_count = int(
        db.scalar(
            select(func.count())
            .select_from(UserGroupMembershipRecord)
            .where(UserGroupMembershipRecord.group_id == group.id)
        )
        or 0
    )
    manager_count = int(
        db.scalar(
            select(func.count())
            .select_from(UserGroupMembershipRecord)
            .where(UserGroupMembershipRecord.group_id == group.id, UserGroupMembershipRecord.role == "manager")
        )
        or 0
    )
    workspace = get_public_workspace(db, group.id)
    return UserGroupSummary(
        groupId=group.id,
        name=group.name,
        description=group.description,
        memberCount=member_count,
        managerCount=manager_count,
        publicWorkspaceId=workspace.id if workspace else None,
        isArchived=group.archived_at is not None,
        createdAt=group.created_at.isoformat(),
    )


def _serialize_request(db: Session, request: UserGroupJoinRequestRecord) -> GroupJoinRequestSummary:
    group = db.get(UserGroupRecord, request.group_id)
    user = db.get(UserRecord, request.user_id)
    if group is None or user is None:
        raise AppError("入组申请关联的用户或用户组不存在。", 404, "GROUP_REQUEST_INVALID")
    return GroupJoinRequestSummary(
        requestId=request.id,
        groupId=group.id,
        groupName=group.name,
        userId=user.id,
        username=user.username,
        displayName=user.display_name,
        status=request.status,
        reviewedByUserId=request.reviewed_by_user_id,
        reviewedAt=request.reviewed_at.isoformat() if request.reviewed_at else None,
        notifyStatus=request.notify_status,
        notifyError=request.notify_error,
        createdAt=request.created_at.isoformat(),
    )


@router.get("/registration", response_model=list[RegistrationGroupSummary])
def registration_groups(db: Session = Depends(get_db)):
    groups = db.scalars(
        select(UserGroupRecord).where(UserGroupRecord.archived_at.is_(None)).order_by(UserGroupRecord.name.asc())
    ).all()
    return [RegistrationGroupSummary(groupId=group.id, name=group.name, description=group.description) for group in groups]


@router.get("/me", response_model=MyGroupStateResponse)
def my_group_state(current_user: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(UserGroupMembershipRecord, UserGroupRecord, WorkspaceRecord)
        .join(UserGroupRecord, UserGroupRecord.id == UserGroupMembershipRecord.group_id)
        .join(WorkspaceRecord, WorkspaceRecord.group_id == UserGroupRecord.id)
        .where(UserGroupMembershipRecord.user_id == current_user.id, WorkspaceRecord.kind == "public")
        .order_by(UserGroupRecord.name.asc())
    ).all()
    memberships = [
        GroupMembershipSummary(
            groupId=group.id,
            name=group.name,
            role=membership.role,
            publicWorkspaceId=workspace.id,
            isArchived=group.archived_at is not None,
        )
        for membership, group, workspace in rows
    ]
    requests = db.scalars(
        select(UserGroupJoinRequestRecord)
        .where(UserGroupJoinRequestRecord.user_id == current_user.id)
        .order_by(UserGroupJoinRequestRecord.created_at.desc())
    ).all()
    return MyGroupStateResponse(memberships=memberships, requests=[_serialize_request(db, item) for item in requests])


@router.post("/requests", response_model=list[GroupJoinRequestSummary])
def request_groups(
    payload: CreateGroupJoinRequestsRequest,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        requests = create_group_join_requests(db, user=current_user, group_ids=payload.groupIds)
        db.commit()
        notify_group_join_requests(db, requests)
        db.commit()
        return [_serialize_request(db, item) for item in requests]
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/requests/{request_id}")
def cancel_group_request(
    request_id: str,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        request = db.get(UserGroupJoinRequestRecord, request_id)
        if request is None or request.user_id != current_user.id:
            raise AppError("入组申请不存在。", 404, "GROUP_REQUEST_NOT_FOUND")
        if request.status != "pending":
            raise AppError("只有待审批申请可以撤回。", 409, "GROUP_REQUEST_NOT_PENDING")
        request.status = "cancelled"
        request.reviewed_at = utc_now()
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.get("/requests/pending", response_model=list[GroupJoinRequestSummary])
def pending_group_requests(
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    query = select(UserGroupJoinRequestRecord).where(UserGroupJoinRequestRecord.status == "pending")
    if not current_user.is_admin:
        managed_ids = db.scalars(
            select(UserGroupMembershipRecord.group_id).where(
                UserGroupMembershipRecord.user_id == current_user.id,
                UserGroupMembershipRecord.role == "manager",
            )
        ).all()
        if not managed_ids:
            return []
        query = query.where(UserGroupJoinRequestRecord.group_id.in_(managed_ids))
    requests = db.scalars(query.order_by(UserGroupJoinRequestRecord.created_at.asc())).all()
    return [_serialize_request(db, item) for item in requests]


@router.patch("/requests/{request_id}", response_model=GroupJoinRequestSummary)
def review_group_request(
    request_id: str,
    payload: ReviewGroupJoinRequest,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        request = db.get(UserGroupJoinRequestRecord, request_id)
        if request is None:
            raise AppError("入组申请不存在。", 404, "GROUP_REQUEST_NOT_FOUND")
        if not can_manage_group(db, request.group_id, current_user):
            raise AppError("只有组管理员或全局管理员可以审批。", 403, "GROUP_MANAGER_REQUIRED")
        if request.status != "pending":
            raise AppError("该申请已经处理。", 409, "GROUP_REQUEST_NOT_PENDING")
        group = db.get(UserGroupRecord, request.group_id)
        user = db.get(UserRecord, request.user_id)
        if group is None or user is None:
            raise AppError("用户或用户组不存在。", 404, "GROUP_REQUEST_INVALID")
        if payload.decision == "approved":
            grant_group_membership(db, group=group, user=user)
        request.status = payload.decision
        request.reviewed_by_user_id = current_user.id
        request.reviewed_at = utc_now()
        db.commit()
        return _serialize_request(db, request)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.get("", response_model=list[UserGroupSummary])
def list_user_groups(_: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    groups = db.scalars(select(UserGroupRecord).order_by(UserGroupRecord.created_at.asc(), UserGroupRecord.name.asc())).all()
    return [_serialize_group(db, group) for group in groups]


@router.post("", response_model=UserGroupSummary)
def create_user_group(
    payload: CreateUserGroupRequest,
    current_user: UserRecord = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        name = payload.name.strip()
        existing = db.scalar(select(UserGroupRecord).where(UserGroupRecord.name == name))
        if existing is not None:
            raise AppError("分组名称已经存在。", 409, "USER_GROUP_NAME_TAKEN")
        group = UserGroupRecord(
            id=f"ug_{uuid.uuid4().hex[:12]}",
            name=name,
            description=payload.description.strip() if payload.description else None,
            created_by_user_id=current_user.id,
            archived_at=None,
            created_at=utc_now(),
        )
        db.add(group)
        db.flush()
        create_public_workspace(db, group)
        set_group_managers(db, group=group, manager_user_ids=payload.managerUserIds or [current_user.id])
        db.commit()
        return _serialize_group(db, group)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.patch("/{group_id}", response_model=UserGroupSummary)
def update_user_group(
    group_id: str,
    payload: UpdateUserGroupRequest,
    _: UserRecord = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        group = db.get(UserGroupRecord, group_id)
        if group is None:
            raise AppError("用户分组不存在。", 404, "USER_GROUP_NOT_FOUND")
        workspace = create_public_workspace(db, group)
        if payload.name is not None:
            name = payload.name.strip()
            duplicate = db.scalar(
                select(UserGroupRecord).where(UserGroupRecord.name == name, UserGroupRecord.id != group.id)
            )
            if duplicate is not None:
                raise AppError("分组名称已经存在。", 409, "USER_GROUP_NAME_TAKEN")
            group.name = name
            workspace.name = f"{name} · Public"
        if payload.description is not None:
            group.description = payload.description.strip() or None
        if payload.managerUserIds is not None:
            set_group_managers(db, group=group, manager_user_ids=payload.managerUserIds)
        if payload.archived is not None:
            group.archived_at = utc_now() if payload.archived else None
            workspace.is_read_only = payload.archived
        db.commit()
        return _serialize_group(db, group)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/{group_id}", response_model=UserGroupSummary)
def archive_user_group(group_id: str, _: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        group = db.get(UserGroupRecord, group_id)
        if group is None:
            raise AppError("用户分组不存在。", 404, "USER_GROUP_NOT_FOUND")
        group.archived_at = utc_now()
        workspace = create_public_workspace(db, group)
        workspace.is_read_only = True
        db.commit()
        return _serialize_group(db, group)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.get("/{group_id}/members", response_model=list[WorkspaceMemberResponse])
def list_group_members(
    group_id: str,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    if not can_manage_group(db, group_id, current_user):
        raise AppError("只有组管理员或全局管理员可以查看完整成员列表。", 403, "GROUP_MANAGER_REQUIRED")
    rows = db.execute(
        select(UserGroupMembershipRecord, UserRecord)
        .join(UserRecord, UserRecord.id == UserGroupMembershipRecord.user_id)
        .where(UserGroupMembershipRecord.group_id == group_id)
        .order_by(UserGroupMembershipRecord.created_at.asc())
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


@router.delete("/{group_id}/members/me")
def leave_group(
    group_id: str,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        group = db.get(UserGroupRecord, group_id)
        if group is None:
            raise AppError("用户分组不存在。", 404, "USER_GROUP_NOT_FOUND")
        remove_group_membership(db, group=group, user=current_user)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/{group_id}/members/{user_id}")
def remove_group_member(
    group_id: str,
    user_id: str,
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        if not can_manage_group(db, group_id, current_user):
            raise AppError("只有组管理员或全局管理员可以移除成员。", 403, "GROUP_MANAGER_REQUIRED")
        group = db.get(UserGroupRecord, group_id)
        user = db.get(UserRecord, user_id)
        if group is None or user is None:
            raise AppError("用户或用户组不存在。", 404, "USER_GROUP_MEMBERSHIP_NOT_FOUND")
        remove_group_membership(db, group=group, user=user)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc
