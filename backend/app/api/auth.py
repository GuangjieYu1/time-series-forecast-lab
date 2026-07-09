from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.core.config import get_settings
from app.core.errors import AppError, as_http_error
from app.core.security import hash_session_token, issue_session_token, session_expiry
from app.db.models import SessionRecord, UserRecord
from app.db.session import get_db
from app.schemas import AuthSessionResponse, AuthUser, BootstrapRequest, LoginRequest, RegisterRequest, UsernameAvailabilityResponse
from app.services.auth_service import count_users, create_user_with_personal_workspace, default_workspace_id, list_workspace_summaries, seed_example_workspace


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalize_username(username: str) -> str:
    return username.strip()


def _username_is_valid(username: str) -> bool:
    normalized = _normalize_username(username)
    return 3 <= len(normalized) <= 120


def _password_meets_registration_rule(password: str) -> bool:
    return len(password) >= 8 and any(char.isalpha() for char in password) and any(char.isdigit() for char in password)


def _serialize_user(user: UserRecord) -> AuthUser:
    return AuthUser(
        userId=user.id,
        username=user.username,
        displayName=user.display_name,
        isAdmin=user.is_admin,
        isActive=user.is_active,
        createdAt=user.created_at.isoformat(),
    )


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=settings.session_ttl_days * 24 * 60 * 60,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie_name, path="/")


def _create_session(db: Session, user_id: str, response: Response) -> None:
    token = issue_session_token()
    record = SessionRecord(
        id=f"session_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        token_hash=hash_session_token(token),
        expires_at=session_expiry(get_settings().session_ttl_days),
    )
    db.add(record)
    db.commit()
    _set_session_cookie(response, token)


def _auth_payload(db: Session, user: UserRecord | None) -> AuthSessionResponse:
    bootstrap_required = count_users(db) == 0
    if user is None:
        return AuthSessionResponse(authenticated=False, bootstrapRequired=bootstrap_required)
    workspaces = list_workspace_summaries(db, user)
    return AuthSessionResponse(
        authenticated=True,
        bootstrapRequired=False,
        user=_serialize_user(user),
        workspaces=workspaces,
        defaultWorkspaceId=default_workspace_id(workspaces),
    )


@router.get("/me", response_model=AuthSessionResponse)
def auth_me(user: UserRecord | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    return _auth_payload(db, user)


@router.get("/username-availability", response_model=UsernameAvailabilityResponse)
def username_availability(username: str = Query(default=""), db: Session = Depends(get_db)):
    normalized = _normalize_username(username)
    if not _username_is_valid(normalized):
        return UsernameAvailabilityResponse(
            available=False,
            normalizedUsername=normalized,
            reason="invalid",
            message="用户名需为 3-120 个字符。",
        )
    existing = db.scalar(select(UserRecord).where(UserRecord.username == normalized))
    if existing is not None:
        return UsernameAvailabilityResponse(
            available=False,
            normalizedUsername=normalized,
            reason="taken",
            message="用户名已被占用。",
        )
    return UsernameAvailabilityResponse(
        available=True,
        normalizedUsername=normalized,
        reason="available",
        message=None,
    )


@router.post("/bootstrap", response_model=AuthSessionResponse)
def bootstrap_auth(payload: BootstrapRequest, response: Response, db: Session = Depends(get_db)):
    try:
        if count_users(db) > 0:
            raise AppError("系统已经初始化，不能再次 bootstrap。", 409, "BOOTSTRAP_DISABLED")
        provisioned = create_user_with_personal_workspace(
            db,
            username=payload.username,
            display_name=payload.displayName,
            password=payload.password,
            is_admin=True,
        )
        seed_example_workspace(db, owner_user_id=provisioned.user.id, backend_root=get_settings().backend_dir)
        db.commit()
        _create_session(db, provisioned.user.id, response)
        refreshed = db.get(UserRecord, provisioned.user.id)
        return _auth_payload(db, refreshed)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    from app.core.security import verify_password

    try:
        user = db.scalar(select(UserRecord).where(UserRecord.username == payload.username.strip()))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise AppError("用户名或密码错误。", 401, "LOGIN_FAILED")
        if not user.is_active:
            raise AppError("当前账号已被禁用。", 403, "USER_DISABLED")
        _create_session(db, user.id, response)
        return _auth_payload(db, user)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.post("/register", response_model=AuthSessionResponse)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    try:
        if count_users(db) == 0:
            raise AppError("系统尚未完成初始化，请先创建第一个管理员账号。", 409, "BOOTSTRAP_REQUIRED")
        normalized_username = _normalize_username(payload.username)
        if not _password_meets_registration_rule(payload.password):
            raise AppError("密码需至少 8 位，且同时包含字母和数字。", 400, "WEAK_PASSWORD")
        existing = db.scalar(select(UserRecord).where(UserRecord.username == normalized_username))
        if existing is not None:
            raise AppError("用户名已经存在。", 409, "USERNAME_TAKEN")
        provisioned = create_user_with_personal_workspace(
            db,
            username=normalized_username,
            display_name=payload.displayName,
            password=payload.password,
            is_admin=False,
        )
        db.commit()
        _create_session(db, provisioned.user.id, response)
        refreshed = db.get(UserRecord, provisioned.user.id)
        return _auth_payload(db, refreshed)
    except AppError as exc:
        db.rollback()
        raise as_http_error(exc) from exc


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: UserRecord | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    try:
        token = request.cookies.get(get_settings().session_cookie_name)
        if token:
            db.execute(delete(SessionRecord).where(SessionRecord.token_hash == hash_session_token(token)))
            db.commit()
        _clear_session_cookie(response)
        return {"ok": True}
    except AppError as exc:
        raise as_http_error(exc) from exc
