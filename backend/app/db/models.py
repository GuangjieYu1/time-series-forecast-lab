from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class UserGroupRecord(Base):
    __tablename__ = "user_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class UserGroupMembershipRecord(Base):
    __tablename__ = "user_group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_user_group_membership"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    is_read_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class WorkspaceMembershipRecord(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_column: Mapped[str] = mapped_column(String(255), nullable=False)
    recommended_model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    best_mae: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_count: Mapped[str] = mapped_column(String(20), default="0")
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    data_profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    backtest_json: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostics_json: Mapped[str] = mapped_column(Text, nullable=False)
    series_json: Mapped[str] = mapped_column(Text, nullable=False)
    final_forecast_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_logs_json: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_file_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    events_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    artifacts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    messages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    invocations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[str | None] = mapped_column(String(512), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    notify_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    notify_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
