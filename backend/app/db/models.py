from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
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
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
