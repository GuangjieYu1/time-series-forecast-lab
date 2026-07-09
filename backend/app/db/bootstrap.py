from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime

from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.db.models import Base
from app.db.schema_compat import ensure_schema_compatibility


def _has_table(sqlite_path, table_name: str) -> bool:
    if not sqlite_path.exists():
        return False
    with sqlite3.connect(sqlite_path) as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def bootstrap_database(engine: Engine) -> None:
    settings = get_settings()
    sqlite_path = settings.data_dir / "forecast_lab.sqlite"
    has_legacy_experiments = _has_table(sqlite_path, "experiments")
    has_users = _has_table(sqlite_path, "users")
    if has_legacy_experiments and not has_users:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = settings.data_backup_dir / f"forecast_lab_legacy_{timestamp}.sqlite"
        engine.dispose()
        shutil.copy2(sqlite_path, backup_path)
        sqlite_path.unlink(missing_ok=True)

    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility(engine)
