from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone

from fastapi import Cookie, Depends, Header, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import hash_session_token, utc_now
from app.db.models import ExperimentRecord, SessionRecord, UserRecord, WorkspaceMembershipRecord, WorkspaceRecord
from app.db.session import get_db
from app.services.auth_service import default_workspace_id, list_workspace_summaries
from app.services.progress_tracker import progress_tracker
from app.services.runtime_tracker import runtime_tracker


@dataclass
class WorkspaceContext:
    user: UserRecord
    workspace: WorkspaceRecord
    membership: WorkspaceMembershipRecord

    @property
    def is_owner(self) -> bool:
        return self.membership.role == "owner"

    @property
    def role(self) -> str:
        return self.membership.role


def _session_cookie_value(
    request: Request,
    cookie_value: str | None,
) -> str | None:
    return cookie_value or request.cookies.get(get_settings().session_cookie_name)


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias="tsfl_session"),
) -> UserRecord | None:
    token = _session_cookie_value(request, session_cookie)
    if not token:
        return None
    session = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == hash_session_token(token)))
    if session is None:
        return None
    now = utc_now()
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        db.delete(session)
        db.commit()
        return None
    user = db.get(UserRecord, session.user_id)
    if user is None or not user.is_active:
        db.delete(session)
        db.commit()
        return None
    session.last_seen_at = now
    db.commit()
    return user


def require_current_user(user: UserRecord | None = Depends(get_optional_current_user)) -> UserRecord:
    if user is None:
        raise AppError("请先登录后再继续。", 401, "AUTH_REQUIRED")
    return user


def require_admin(user: UserRecord = Depends(require_current_user)) -> UserRecord:
    if not user.is_admin:
        raise AppError("只有管理员可以执行此操作。", 403, "ADMIN_REQUIRED")
    return user


def _requested_workspace_id(
    x_workspace_id: str | None,
    workspace_query_id: str | None,
) -> str | None:
    return (x_workspace_id or workspace_query_id or "").strip() or None


def get_workspace_context(
    current_user: UserRecord = Depends(require_current_user),
    db: Session = Depends(get_db),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    workspace_query_id: str | None = Query(default=None, alias="workspaceId"),
) -> WorkspaceContext:
    requested_id = _requested_workspace_id(x_workspace_id, workspace_query_id)
    if requested_id is None:
        workspaces = list_workspace_summaries(db, current_user)
        requested_id = default_workspace_id(workspaces)
    if not requested_id:
        raise AppError("当前用户还没有可用工作区。", 403, "WORKSPACE_NOT_AVAILABLE")
    row = db.execute(
        select(WorkspaceMembershipRecord, WorkspaceRecord)
        .join(WorkspaceRecord, WorkspaceRecord.id == WorkspaceMembershipRecord.workspace_id)
        .where(
            WorkspaceMembershipRecord.user_id == current_user.id,
            WorkspaceMembershipRecord.workspace_id == requested_id,
        )
    ).first()
    if row is None:
        raise AppError("当前工作区不存在或你没有访问权限。", 403, "WORKSPACE_FORBIDDEN")
    membership, workspace = row
    return WorkspaceContext(user=current_user, workspace=workspace, membership=membership)


def require_workspace_write_access(context: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
    if context.workspace.is_read_only:
        raise AppError("当前工作区是只读 Example 空间，不能执行写操作。", 403, "WORKSPACE_READ_ONLY")
    return context


def require_workspace_owner(context: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
    if context.workspace.kind != "shared":
        raise AppError("只有共享工作区支持成员管理。", 403, "WORKSPACE_OWNER_REQUIRED")
    if not context.is_owner:
        raise AppError("只有工作区 owner 可以执行此操作。", 403, "WORKSPACE_OWNER_REQUIRED")
    if context.workspace.is_read_only:
        raise AppError("Example 工作区是只读空间，不能执行此操作。", 403, "WORKSPACE_READ_ONLY")
    return context


def get_workspace_experiment(db: Session, experiment_id: str, context: WorkspaceContext) -> ExperimentRecord:
    record = db.get(ExperimentRecord, experiment_id)
    if record is None:
        raise AppError("Experiment was not found.", 404)
    if record.workspace_id != context.workspace.id:
        raise AppError("这个实验不属于当前工作区。", 403, "EXPERIMENT_WORKSPACE_FORBIDDEN")
    return record


def ensure_runtime_scope(runtime_id: str, context: WorkspaceContext, db: Session) -> None:
    live_scope = runtime_tracker.get_scope(runtime_id)
    if live_scope is not None:
        if live_scope["workspaceId"] != context.workspace.id or live_scope["userId"] != context.user.id:
            raise AppError("这个运行实例不属于当前工作区。", 403, "RUNTIME_WORKSPACE_FORBIDDEN")
        return
    record = db.get(ExperimentRecord, runtime_id)
    if record is None:
        alias = runtime_tracker.resolve_runtime_id(runtime_id)
        if alias != runtime_id:
            live_scope = runtime_tracker.get_scope(alias)
            if live_scope is None or live_scope["workspaceId"] != context.workspace.id:
                raise AppError("这个运行实例不属于当前工作区。", 403, "RUNTIME_WORKSPACE_FORBIDDEN")
            return
        raise AppError("Runtime detail was not found.", 404, "RUNTIME_NOT_FOUND")
    if record.workspace_id != context.workspace.id:
        raise AppError("这个运行实例不属于当前工作区。", 403, "RUNTIME_WORKSPACE_FORBIDDEN")


def ensure_progress_scope(run_id: str, context: WorkspaceContext) -> None:
    scope = progress_tracker.get_scope(run_id)
    if scope is None:
        raise AppError("Forecast progress was not found.", 404, "PROGRESS_NOT_FOUND")
    if scope["workspaceId"] != context.workspace.id or scope["userId"] != context.user.id:
        raise AppError("这个运行实例不属于当前工作区。", 403, "PROGRESS_WORKSPACE_FORBIDDEN")


def invalidate_user_sessions(db: Session, user_id: str) -> None:
    db.execute(delete(SessionRecord).where(SessionRecord.user_id == user_id))
