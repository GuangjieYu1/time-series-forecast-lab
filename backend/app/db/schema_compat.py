from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


EXPERIMENT_COLUMN_DEFINITIONS = {
    "manifest_json": "TEXT",
    "config_hash": "VARCHAR(128)",
    "source_file_sha256": "VARCHAR(128)",
    "app_version": "VARCHAR(32)",
    "git_commit": "VARCHAR(64)",
}


def ensure_schema_compatibility(engine: Engine) -> None:
    inspector = inspect(engine)
    if "experiments" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("experiments")}
    missing = {
        name: definition
        for name, definition in EXPERIMENT_COLUMN_DEFINITIONS.items()
        if name not in existing_columns
    }
    if not missing:
        return

    with engine.begin() as connection:
        for column_name, column_type in missing.items():
            connection.execute(text(f"ALTER TABLE experiments ADD COLUMN {column_name} {column_type}"))
