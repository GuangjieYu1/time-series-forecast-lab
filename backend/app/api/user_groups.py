from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.errors import AppError, as_http_error
from app.core.security import utc_now
from app.db.models import UserGroupMembershipRecord, UserGroupRecord, UserRecord
from app.db.session import get_db
from app.schemas import CreateUserGroupRequest, UserGroupSummary


router = APIRouter(prefix="/api/user-groups", tags=["user-groups"])


def _serialize_group(group: UserGroupRecord, member_count: int) -> UserGroupSummary:
    return UserGroupSummary(
        groupId=group.id,
        name=group.name,
        description=group.description,
        memberCount=member_count,
        createdAt=group.created_at.isoformat(),
    )


@router.get("", response_model=list[UserGroupSummary])
def list_user_groups(_: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(UserGroupRecord, func.count(UserGroupMembershipRecord.id))
        .outerjoin(UserGroupMembershipRecord, UserGroupMembershipRecord.group_id == UserGroupRecord.id)
        .group_by(UserGroupRecord.id)
        .order_by(UserGroupRecord.created_at.asc(), UserGroupRecord.name.asc())
    ).all()
    return [_serialize_group(group, int(member_count or 0)) for group, member_count in rows]


@router.post("", response_model=UserGroupSummary)
def create_user_group(
    payload: CreateUserGroupRequest,
    current_user: UserRecord = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        name = payload.name.strip()
        if not name:
            raise AppError("分组名称不能为空。", 400, "USER_GROUP_NAME_REQUIRED")
        existing = db.scalar(select(UserGroupRecord).where(UserGroupRecord.name == name))
        if existing is not None:
            raise AppError("分组名称已经存在。", 409, "USER_GROUP_NAME_TAKEN")
        description = payload.description.strip() if payload.description else None
        group = UserGroupRecord(
            id=f"ug_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description or None,
            created_by_user_id=current_user.id,
            created_at=utc_now(),
        )
        db.add(group)
        db.commit()
        return _serialize_group(group, 0)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.delete("/{group_id}")
def delete_user_group(group_id: str, _: UserRecord = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        group = db.get(UserGroupRecord, group_id)
        if group is None:
            raise AppError("用户分组不存在。", 404, "USER_GROUP_NOT_FOUND")
        db.execute(delete(UserGroupMembershipRecord).where(UserGroupMembershipRecord.group_id == group_id))
        db.delete(group)
        db.commit()
        return {"ok": True}
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc
