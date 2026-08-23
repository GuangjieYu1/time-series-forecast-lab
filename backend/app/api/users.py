from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import invalidate_user_sessions, require_admin, require_current_user
from app.core.errors import AppError, as_http_error
from app.core.security import password_hash
from app.db.models import UserGroupMembershipRecord, UserGroupRecord, UserRecord
from app.db.session import get_db
from app.schemas import (
    CreateUserRequest,
    UpdateUserGroupsRequest,
    UpdateUserPasswordRequest,
    UpdateUserRequest,
    UserDirectoryEntry,
    UserGroupRef,
    UserSummary,
)
from app.services.auth_service import create_user_with_personal_workspace
from app.services.group_service import get_group_membership, grant_group_membership, remove_group_membership


router = APIRouter(prefix="/api/users", tags=["users"])


def _load_group_refs_by_user(db: Session, user_ids: list[str]) -> dict[str, list[UserGroupRef]]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(
            UserGroupMembershipRecord.user_id,
            UserGroupRecord.id,
            UserGroupRecord.name,
            UserGroupMembershipRecord.role,
            UserGroupRecord.archived_at,
        )
        .join(UserGroupRecord, UserGroupRecord.id == UserGroupMembershipRecord.group_id)
        .where(UserGroupMembershipRecord.user_id.in_(user_ids))
        .order_by(UserGroupRecord.name.asc())
    ).all()
    mapping: dict[str, list[UserGroupRef]] = {user_id: [] for user_id in user_ids}
    for user_id, group_id, group_name, role, archived_at in rows:
        mapping.setdefault(user_id, []).append(
            UserGroupRef(groupId=group_id, name=group_name, role=role, isArchived=archived_at is not None)
        )
    return mapping


def _serialize_user(user: UserRecord, groups: list[UserGroupRef] | None = None) -> UserSummary:
    return UserSummary(
        userId=user.id,
        username=user.username,
        displayName=user.display_name,
        isAdmin=user.is_admin,
        isActive=user.is_active,
        createdAt=user.created_at.isoformat(),
        groups=groups or [],
    )


def _ensure_not_last_active_group_manager(db: Session, user: UserRecord) -> None:
    managed_memberships = db.scalars(
        select(UserGroupMembershipRecord).where(
            UserGroupMembershipRecord.user_id == user.id,
            UserGroupMembershipRecord.role == "manager",
        )
    ).all()
    for membership in managed_memberships:
        other_active_manager_count = int(
            db.scalar(
                select(func.count())
                .select_from(UserGroupMembershipRecord)
                .join(UserRecord, UserRecord.id == UserGroupMembershipRecord.user_id)
                .where(
                    UserGroupMembershipRecord.group_id == membership.group_id,
                    UserGroupMembershipRecord.role == "manager",
                    UserGroupMembershipRecord.user_id != user.id,
                    UserRecord.is_active.is_(True),
                )
            )
            or 0
        )
        if other_active_manager_count == 0:
            group = db.get(UserGroupRecord, membership.group_id)
            group_name = group.name if group is not None else membership.group_id
            raise AppError(
                f"不能停用用户：其仍是用户组「{group_name}」最后一名活跃管理员。",
                409,
                "LAST_ACTIVE_GROUP_MANAGER",
            )


@router.get("", response_model=list[UserSummary])
def list_users(_: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(UserRecord).order_by(UserRecord.created_at.asc())).all()
    groups_by_user = _load_group_refs_by_user(db, [user.id for user in users])
    return [_serialize_user(user, groups_by_user.get(user.id, [])) for user in users]


@router.get("/directory", response_model=list[UserDirectoryEntry])
def user_directory(_: UserRecord = Depends(require_current_user), db: Session = Depends(get_db)):
    users = db.scalars(
        select(UserRecord)
        .where(UserRecord.is_active.is_(True))
        .order_by(UserRecord.display_name.asc(), UserRecord.username.asc())
    ).all()
    return [UserDirectoryEntry(userId=user.id, username=user.username, displayName=user.display_name) for user in users]


@router.post("", response_model=UserSummary)
def create_user(payload: CreateUserRequest, _: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        existing = db.scalar(select(UserRecord).where(UserRecord.username == payload.username.strip()))
        if existing is not None:
            raise AppError("用户名已经存在。", 409, "USERNAME_TAKEN")
        created = create_user_with_personal_workspace(
            db,
            username=payload.username,
            display_name=payload.displayName,
            password=payload.password,
            is_admin=payload.isAdmin,
        )
        group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.groupIds if group_id.strip()))
        groups = db.scalars(select(UserGroupRecord).where(UserGroupRecord.id.in_(group_ids))).all() if group_ids else []
        if len(groups) != len(group_ids):
            raise AppError("存在无效的用户分组。", 404, "USER_GROUP_NOT_FOUND")
        groups_by_id = {group.id: group for group in groups}
        for group_id in group_ids:
            grant_group_membership(db, group=groups_by_id[group_id], user=created.user)
        db.commit()
        groups_by_user = _load_group_refs_by_user(db, [created.user.id])
        return _serialize_user(created.user, groups_by_user.get(created.user.id, []))
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.patch("/{user_id}", response_model=UserSummary)
def update_user(user_id: str, payload: UpdateUserRequest, _: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        user = db.get(UserRecord, user_id)
        if user is None:
            raise AppError("用户不存在。", 404, "USER_NOT_FOUND")
        if payload.displayName is not None:
            user.display_name = payload.displayName.strip()
        if payload.isActive is not None:
            if user.is_active and not payload.isActive:
                _ensure_not_last_active_group_manager(db, user)
            user.is_active = payload.isActive
            if not user.is_active:
                invalidate_user_sessions(db, user.id)
        db.commit()
        groups_by_user = _load_group_refs_by_user(db, [user.id])
        return _serialize_user(user, groups_by_user.get(user.id, []))
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.put("/{user_id}/groups", response_model=UserSummary)
def update_user_groups(
    user_id: str,
    payload: UpdateUserGroupsRequest,
    _: UserRecord = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        user = db.get(UserRecord, user_id)
        if user is None:
            raise AppError("用户不存在。", 404, "USER_NOT_FOUND")
        group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.groupIds if group_id.strip()))
        groups = db.scalars(select(UserGroupRecord).where(UserGroupRecord.id.in_(group_ids))).all() if group_ids else []
        if len(groups) != len(group_ids):
            raise AppError("存在无效的用户分组。", 404, "USER_GROUP_NOT_FOUND")
        groups_by_id = {group.id: group for group in groups}
        current_memberships = db.scalars(
            select(UserGroupMembershipRecord).where(UserGroupMembershipRecord.user_id == user_id)
        ).all()
        requested = set(group_ids)
        for membership in current_memberships:
            if membership.group_id not in requested:
                group = db.get(UserGroupRecord, membership.group_id)
                if group is not None:
                    remove_group_membership(db, group=group, user=user)
        for group_id in group_ids:
            if get_group_membership(db, group_id, user_id) is None:
                grant_group_membership(db, group=groups_by_id[group_id], user=user)
        db.commit()
        groups_by_user = _load_group_refs_by_user(db, [user.id])
        return _serialize_user(user, groups_by_user.get(user.id, []))
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.patch("/{user_id}/password")
def update_user_password(
    user_id: str,
    payload: UpdateUserPasswordRequest,
    _: UserRecord = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        user = db.get(UserRecord, user_id)
        if user is None:
            raise AppError("用户不存在。", 404, "USER_NOT_FOUND")
        user.password_hash = password_hash(payload.password)
        invalidate_user_sessions(db, user.id)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc
