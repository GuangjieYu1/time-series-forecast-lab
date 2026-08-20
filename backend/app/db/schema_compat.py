from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


EXPERIMENT_COMPAT_COLUMNS: dict[str, str] = {
    "analysis_type": "TEXT DEFAULT 'forecast'",
    "parent_upload_id": "TEXT",
    "source_experiment_id": "TEXT",
    "dataset_profile_json": "TEXT",
    "manifest_json": "TEXT",
    "attribution_json": "TEXT",
    "workflow_state_json": "TEXT",
    "artifacts_json": "TEXT DEFAULT '[]'",
    "config_hash": "TEXT",
    "source_file_sha256": "TEXT",
    "app_version": "TEXT",
    "git_commit": "TEXT",
}

AGENT_RUN_COMPAT_COLUMNS: dict[str, str] = {
    "conversation_json": "TEXT DEFAULT '[]'",
    "llm_session_json": "TEXT",
}

USER_GROUP_COMPAT_COLUMNS: dict[str, str] = {
    "archived_at": "DATETIME",
}

USER_GROUP_MEMBERSHIP_COMPAT_COLUMNS: dict[str, str] = {
    "role": "TEXT NOT NULL DEFAULT 'member'",
}

WORKSPACE_COMPAT_COLUMNS: dict[str, str] = {
    "group_id": "TEXT",
}


def _add_missing_columns(connection, inspector, table_name: str, columns: dict[str, str]) -> None:
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column_name, column_type in columns.items():
        if column_name not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _migrate_workspace_model(connection) -> None:
    connection.execute(text("UPDATE workspaces SET kind = 'private' WHERE kind = 'personal'"))
    connection.execute(text("UPDATE workspaces SET kind = 'custom' WHERE kind = 'shared'"))
    connection.execute(text("UPDATE user_group_memberships SET role = 'member' WHERE role IS NULL OR role = ''"))

    now = datetime.now(timezone.utc)
    groups = connection.execute(
        text("SELECT id, name, created_by_user_id, archived_at FROM user_groups ORDER BY created_at ASC")
    ).mappings().all()
    for group in groups:
        group_id = str(group["id"])
        creator_id = str(group["created_by_user_id"])
        manager = connection.execute(
            text("SELECT id FROM user_group_memberships WHERE group_id = :group_id AND user_id = :user_id"),
            {"group_id": group_id, "user_id": creator_id},
        ).first()
        if manager:
            connection.execute(
                text("UPDATE user_group_memberships SET role = 'manager' WHERE group_id = :group_id AND user_id = :user_id"),
                {"group_id": group_id, "user_id": creator_id},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO user_group_memberships (id, group_id, user_id, role, created_at) "
                    "VALUES (:id, :group_id, :user_id, 'manager', :created_at)"
                ),
                {"id": f"ugm_{uuid.uuid4().hex[:12]}", "group_id": group_id, "user_id": creator_id, "created_at": now},
            )

        public_workspace = connection.execute(
            text("SELECT id FROM workspaces WHERE kind = 'public' AND group_id = :group_id"),
            {"group_id": group_id},
        ).first()
        if public_workspace:
            workspace_id = str(public_workspace[0])
        else:
            workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, name, kind, owner_user_id, group_id, is_read_only, created_at) "
                    "VALUES (:id, :name, 'public', :owner_user_id, :group_id, :is_read_only, :created_at)"
                ),
                {
                    "id": workspace_id,
                    "name": f"{group['name']} · Public",
                    "owner_user_id": creator_id,
                    "group_id": group_id,
                    "is_read_only": bool(group["archived_at"]),
                    "created_at": now,
                },
            )

        memberships = connection.execute(
            text("SELECT user_id, role, created_at FROM user_group_memberships WHERE group_id = :group_id"),
            {"group_id": group_id},
        ).mappings().all()
        for membership in memberships:
            exists = connection.execute(
                text("SELECT id FROM workspace_memberships WHERE workspace_id = :workspace_id AND user_id = :user_id"),
                {"workspace_id": workspace_id, "user_id": membership["user_id"]},
            ).first()
            role = "manager" if membership["role"] == "manager" else "member"
            if exists:
                connection.execute(
                    text("UPDATE workspace_memberships SET role = :role WHERE workspace_id = :workspace_id AND user_id = :user_id"),
                    {"role": role, "workspace_id": workspace_id, "user_id": membership["user_id"]},
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO workspace_memberships (id, workspace_id, user_id, role, created_at) "
                        "VALUES (:id, :workspace_id, :user_id, :role, :created_at)"
                    ),
                    {
                        "id": f"wm_{uuid.uuid4().hex[:12]}",
                        "workspace_id": workspace_id,
                        "user_id": membership["user_id"],
                        "role": role,
                        "created_at": membership["created_at"] or now,
                    },
                )

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_workspaces_public_group "
            "ON workspaces(group_id) WHERE group_id IS NOT NULL AND kind = 'public'"
        )
    )


def ensure_schema_compatibility(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        _add_missing_columns(connection, inspector, "experiments", EXPERIMENT_COMPAT_COLUMNS)
        _add_missing_columns(connection, inspector, "agent_runs", AGENT_RUN_COMPAT_COLUMNS)
        _add_missing_columns(connection, inspector, "user_groups", USER_GROUP_COMPAT_COLUMNS)
        _add_missing_columns(connection, inspector, "user_group_memberships", USER_GROUP_MEMBERSHIP_COMPAT_COLUMNS)
        _add_missing_columns(connection, inspector, "workspaces", WORKSPACE_COMPAT_COLUMNS)
        if {"users", "user_groups", "user_group_memberships", "workspaces", "workspace_memberships"}.issubset(
            set(inspector.get_table_names())
        ):
            _migrate_workspace_model(connection)
