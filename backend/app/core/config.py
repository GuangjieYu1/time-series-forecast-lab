from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Time Series Forecast Lab"
    backend_dir: Path = Path(__file__).resolve().parents[2]
    repo_root: Path = Path(__file__).resolve().parents[3]
    max_upload_mb: int = 100
    temp_upload_ttl_hours: int = 12
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    local_rebuild_password: str | None = None
    local_rebuild_password_file: Path | None = None
    local_rebuild_allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1", "localhost"])
    wecom_feedback_webhook_url: str | None = None
    feedback_notification_timeout_seconds: float = 5.0
    session_cookie_name: str = "tsfl_session"
    session_ttl_days: int = 30

    @property
    def upload_dir(self) -> Path:
        return self.backend_dir / "tmp" / "uploads"

    @property
    def data_dir(self) -> Path:
        return self.backend_dir / "data"

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'forecast_lab.sqlite'}"

    @property
    def model_cache_dir(self) -> Path:
        return self.backend_dir / ".model_cache"

    @property
    def deploy_dir(self) -> Path:
        return self.repo_root / "deploy"

    @property
    def data_backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def resolved_local_rebuild_password(self) -> str | None:
        if self.local_rebuild_password:
            return self.local_rebuild_password
        candidate = self.local_rebuild_password_file or (self.deploy_dir / ".local-rebuild-password")
        try:
            if candidate.exists():
                value = candidate.read_text(encoding="utf-8").strip()
                return value or None
        except OSError:
            return None
        return None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.data_backup_dir.mkdir(parents=True, exist_ok=True)
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
