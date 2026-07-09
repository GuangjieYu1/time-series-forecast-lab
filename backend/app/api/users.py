from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.dependencies import invalidate_user_sessions, require_admin
from app.core.errors import AppError, as_http_error
from app.core.security import utc_now
from app.core.security import password_hash
from app.db.models import UserGroupMembershipRecord, UserGroupRecord, UserRecord
from app.db.session import get_db
from app.schemas import CreateUserRequest, UpdateUserGroupsRequest, UpdateUserPasswordRequest, UpdateUserRequest, UserGroupRef, UserSummary
from app.services.auth_service import create_user_with_personal_workspace


router = APIRouter(prefix="/api/users", tags=["users"])


def _load_group_refs_by_user(db: Session, user_ids: list[str]) -> dict[str, list[UserGroupRef]]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(UserGroupMembershipRecord.user_id, UserGroupRecord.id, UserGroupRecord.name)
        .join(UserGroupRecord, UserGroupRecord.id == UserGroupMembershipRecord.group_id)
        .where(UserGroupMembershipRecord.user_id.in_(user_ids))
        .order_by(UserGroupRecord.name.asc())
    ).all()
    mapping: dict[str, list[UserGroupRef]] = {user_id: [] for user_id in user_ids}
    for user_id, group_id, group_name in rows:
        mapping.setdefault(user_id, []).append(UserGroupRef(groupId=group_id, name=group_name))
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


@router.get("", response_model=list[UserSummary])
def list_users(_: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(UserRecord).order_by(UserRecord.created_at.asc())).all()
    groups_by_user = _load_group_refs_by_user(db, [user.id for user in users])
    return [_serialize_user(user, groups_by_user.get(user.id, [])) for user in users]


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
        db.commit()
        return _serialize_user(created.user)
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

        normalized_group_ids = list(dict.fromkeys(group_id.strip() for group_id in payload.groupIds if group_id.strip()))
        groups: list[UserGroupRecord] = []
        if normalized_group_ids:
            groups = db.scalars(select(UserGroupRecord).where(UserGroupRecord.id.in_(normalized_group_ids))).all()
            if len(groups) != len(normalized_group_ids):
                raise AppError("存在无效的用户分组。", 404, "USER_GROUP_NOT_FOUND")
        groups_by_id = {group.id: group for group in groups}

        db.execute(delete(UserGroupMembershipRecord).where(UserGroupMembershipRecord.user_id == user_id))
        now = utc_now()
        for group_id in normalized_group_ids:
            db.add(
                UserGroupMembershipRecord(
                    id=f"ugm_{uuid.uuid4().hex[:12]}",
                    group_id=group_id,
                    user_id=user_id,
                    created_at=now,
                )
            )
        db.commit()
        ordered_refs = [UserGroupRef(groupId=group_id, name=groups_by_id[group_id].name) for group_id in normalized_group_ids]
        return _serialize_user(user, ordered_refs)
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
