from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


EXPERIMENT_COMPAT_COLUMNS: dict[str, str] = {
    "manifest_json": "TEXT",
    "attribution_json": "TEXT",
    "config_hash": "TEXT",
    "source_file_sha256": "TEXT",
    "app_version": "TEXT",
    "git_commit": "TEXT",
}


def ensure_schema_compatibility(engine: Engine) -> None:
    inspector = inspect(engine)
    if "experiments" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("experiments")}
    missing = [(name, ddl) for name, ddl in EXPERIMENT_COMPAT_COLUMNS.items() if name not in existing_columns]
    if not missing:
        return

    with engine.begin() as connection:
        for column_name, column_type in missing:
            connection.execute(text(f"ALTER TABLE experiments ADD COLUMN {column_name} {column_type}"))
