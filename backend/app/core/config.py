from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Time Series Forecast Lab"
    backend_dir: Path = Path(__file__).resolve().parents[2]
    max_upload_mb: int = 100
    temp_upload_ttl_hours: int = 12
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
