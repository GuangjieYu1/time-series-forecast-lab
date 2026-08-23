from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, ExperimentRecord, ReportRecord
from app.db.schema_compat import ensure_schema_compatibility
from app.db.session import get_db
from app.main import app


@dataclass
class GroupTestEnv:
    session_local: sessionmaker

    def client(self) -> TestClient:
        return TestClient(app)


@pytest.fixture()
def group_env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'group-spaces.sqlite'}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield GroupTestEnv(session_local=testing_session_local)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _bootstrap(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "displayName": "Admin", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _register(client: TestClient, username: str, requested_group_ids: list[str]) -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "displayName": username.upper(),
            "password": "password123",
            "requestedGroupIds": requested_group_ids,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(client: TestClient, username: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()


def _add_experiment(db, *, experiment_id: str, workspace_id: str, creator_id: str) -> None:
    db.add(
        ExperimentRecord(
            id=experiment_id,
            workspace_id=workspace_id,
            created_by_user_id=creator_id,
            name=experiment_id,
            file_name="demo.xlsx",
            sheet_name="Sheet1",
            target_column="value",
            recommended_model_id="naive",
            best_mae="1.0",
            model_count="1",
            config_json="{}",
            data_profile_json="{}",
            metrics_json="[]",
            backtest_json="{}",
            diagnostics_json="{}",
            series_json="[]",
            model_logs_json="[]",
        )
    )


def test_private_public_custom_requests_permissions_and_move(group_env: GroupTestEnv, monkeypatch):
    def fail_group_notification(**_):
        raise ValueError("simulated malformed webhook")

    monkeypatch.setattr("app.services.group_service.notify_group_join_request", fail_group_notification)
    admin = group_env.client()
    admin_session = _bootstrap(admin)
    admin_id = admin_session["user"]["userId"]

    group_one_response = admin.post(
        "/api/user-groups",
        json={"name": "Data Team", "description": "group one", "managerUserIds": [admin_id]},
    )
    group_two_response = admin.post(
        "/api/user-groups",
        json={"name": "Ops Team", "description": "group two", "managerUserIds": [admin_id]},
    )
    assert group_one_response.status_code == 200, group_one_response.text
    assert group_two_response.status_code == 200, group_two_response.text
    group_one = group_one_response.json()
    group_two = group_two_response.json()
    cannot_deactivate_last_active_manager = admin.patch(
        f"/api/users/{admin_id}",
        json={"isActive": False},
    )
    assert cannot_deactivate_last_active_manager.status_code == 409

    user_a = group_env.client()
    user_b = group_env.client()
    user_c = group_env.client()
    a_registered = _register(user_a, "user_a", [group_one["groupId"], group_two["groupId"]])
    b_registered = _register(user_b, "user_b", [group_one["groupId"]])
    c_registered = _register(user_c, "user_c", [])
    user_a_id = a_registered["user"]["userId"]
    user_b_id = b_registered["user"]["userId"]
    user_c_id = c_registered["user"]["userId"]

    assert {workspace["kind"] for workspace in a_registered["workspaces"]} == {"private", "example"}
    assert all(workspace["kind"] != "public" for workspace in b_registered["workspaces"])
    a_state_before = user_a.get("/api/user-groups/me").json()
    assert len(a_state_before["requests"]) == 2
    assert all(request["notifyStatus"] == "failed" for request in a_state_before["requests"])

    forbidden_review = user_b.patch(
        f"/api/user-groups/requests/{a_state_before['requests'][0]['requestId']}",
        json={"decision": "approved"},
    )
    assert forbidden_review.status_code == 403

    pending = admin.get("/api/user-groups/requests/pending")
    assert pending.status_code == 200, pending.text
    assert len(pending.json()) == 3
    for request in pending.json():
        approved = admin.patch(
            f"/api/user-groups/requests/{request['requestId']}",
            json={"decision": "approved"},
        )
        assert approved.status_code == 200, approved.text

    promoted = admin.patch(
        f"/api/user-groups/{group_one['groupId']}",
        json={"managerUserIds": [admin_id, user_b_id]},
    )
    assert promoted.status_code == 200, promoted.text
    user_d = group_env.client()
    _register(user_d, "user_d", [])
    d_request = user_d.post("/api/user-groups/requests", json={"groupIds": [group_one["groupId"]]})
    assert d_request.status_code == 200, d_request.text
    manager_approved = user_b.patch(
        f"/api/user-groups/requests/{d_request.json()[0]['requestId']}",
        json={"decision": "approved"},
    )
    assert manager_approved.status_code == 200, manager_approved.text
    d_session = _login(user_d, "user_d")
    assert group_one["publicWorkspaceId"] in {
        workspace["workspaceId"] for workspace in d_session["workspaces"]
    }

    a_session = _login(user_a, "user_a")
    b_session = _login(user_b, "user_b")
    a_public = [workspace for workspace in a_session["workspaces"] if workspace["kind"] == "public"]
    b_public = [workspace for workspace in b_session["workspaces"] if workspace["kind"] == "public"]
    assert len(a_public) == 2
    assert len(b_public) == 1
    public_workspace_id = group_one["publicWorkspaceId"]
    assert public_workspace_id in {workspace["workspaceId"] for workspace in a_public}
    assert public_workspace_id == b_public[0]["workspaceId"]

    directory = user_a.get("/api/users/directory")
    assert directory.status_code == 200
    assert {"userId", "username", "displayName"} == set(directory.json()[0])
    inactive = admin.post(
        "/api/users",
        json={"username": "inactive_user", "displayName": "Inactive User", "password": "password123", "isAdmin": False},
    )
    assert inactive.status_code == 200, inactive.text
    deactivated = admin.patch(f"/api/users/{inactive.json()['userId']}", json={"isActive": False})
    assert deactivated.status_code == 200, deactivated.text
    active_directory_ids = {entry["userId"] for entry in user_a.get("/api/users/directory").json()}
    assert inactive.json()["userId"] not in active_directory_ids

    custom = user_a.post(
        "/api/workspaces",
        json={"name": "Cross Group Project", "memberUserIds": [user_b_id, user_c_id]},
    )
    assert custom.status_code == 200, custom.text
    custom_workspace_id = custom.json()["workspaceId"]
    assert custom_workspace_id in {workspace["workspaceId"] for workspace in _login(user_c, "user_c")["workspaces"]}

    user_a.headers.update({"X-Workspace-Id": custom_workspace_id})
    updated_members = user_a.put(
        f"/api/workspaces/{custom_workspace_id}/members",
        json={"memberUserIds": [user_c_id]},
    )
    assert updated_members.status_code == 200, updated_members.text
    user_b.headers.update({"X-Workspace-Id": custom_workspace_id})
    assert user_b.get("/api/experiments").status_code == 403

    with group_env.session_local() as db:
        _add_experiment(db, experiment_id="exp_move", workspace_id=public_workspace_id, creator_id=user_a_id)
        db.add(
            ReportRecord(
                id="report_move",
                experiment_id="exp_move",
                workspace_id=public_workspace_id,
                created_by_user_id=user_a_id,
                content_markdown="report",
                model="test",
            )
        )
        db.commit()

    user_d.headers.update({"X-Workspace-Id": public_workspace_id})
    assert any(item["experimentId"] == "exp_move" for item in user_d.get("/api/experiments").json())
    assert user_d.delete("/api/experiments/exp_move").status_code == 403
    d_private_id = next(workspace["workspaceId"] for workspace in d_session["workspaces"] if workspace["kind"] == "private")
    forbidden_move = user_d.post("/api/experiments/exp_move/move", json={"targetWorkspaceId": d_private_id})
    assert forbidden_move.status_code == 403

    b_private_id = next(workspace["workspaceId"] for workspace in b_session["workspaces"] if workspace["kind"] == "private")
    user_b.headers.update({"X-Workspace-Id": public_workspace_id})
    manager_move = user_b.post("/api/experiments/exp_move/move", json={"targetWorkspaceId": b_private_id})
    assert manager_move.status_code == 200, manager_move.text
    user_b.headers.update({"X-Workspace-Id": b_private_id})
    manager_move_back = user_b.post("/api/experiments/exp_move/move", json={"targetWorkspaceId": public_workspace_id})
    assert manager_move_back.status_code == 200, manager_move_back.text
    with group_env.session_local() as db:
        manager_moved_experiment = db.get(ExperimentRecord, "exp_move")
        manager_moved_report = db.get(ReportRecord, "report_move")
        assert manager_moved_experiment is not None and manager_moved_experiment.workspace_id == public_workspace_id
        assert manager_moved_experiment.created_by_user_id == user_a_id
        assert manager_moved_report is not None and manager_moved_report.workspace_id == public_workspace_id

    a_private_id = next(workspace["workspaceId"] for workspace in a_session["workspaces"] if workspace["kind"] == "private")
    user_a.headers.update({"X-Workspace-Id": public_workspace_id})
    moved = user_a.post("/api/experiments/exp_move/move", json={"targetWorkspaceId": a_private_id})
    assert moved.status_code == 200, moved.text
    with group_env.session_local() as db:
        experiment = db.get(ExperimentRecord, "exp_move")
        report = db.get(ReportRecord, "report_move")
        assert experiment is not None and experiment.workspace_id == a_private_id
        assert experiment.created_by_user_id == user_a_id
        assert report is not None and report.workspace_id == a_private_id

        _add_experiment(db, experiment_id="exp_history", workspace_id=public_workspace_id, creator_id=user_a_id)
        db.commit()

    user_b.headers.update({"X-Workspace-Id": public_workspace_id})
    left = user_b.delete(f"/api/user-groups/{group_one['groupId']}/members/me")
    assert left.status_code == 200, left.text
    assert all(workspace["workspaceId"] != public_workspace_id for workspace in user_b.get("/api/auth/me").json()["workspaces"])
    assert user_b.get("/api/experiments").status_code == 403
    with group_env.session_local() as db:
        assert db.get(ExperimentRecord, "exp_history") is not None

    archived = admin.delete(f"/api/user-groups/{group_one['groupId']}")
    assert archived.status_code == 200, archived.text
    assert archived.json()["isArchived"] is True
    refreshed_a = user_a.get("/api/auth/me").json()
    archived_public = next(workspace for workspace in refreshed_a["workspaces"] if workspace["workspaceId"] == public_workspace_id)
    assert archived_public["isReadOnly"] is True

    user_a.headers.update({"X-Workspace-Id": public_workspace_id})
    assert user_a.delete("/api/experiments/exp_history").status_code == 403
    admin.headers.update({"X-Workspace-Id": public_workspace_id})
    assert admin.delete("/api/experiments/exp_history").status_code == 200
    cannot_leave_last_manager = admin.delete(f"/api/user-groups/{group_one['groupId']}/members/me")
    assert cannot_leave_last_manager.status_code == 409
    archived_request = user_c.post("/api/user-groups/requests", json={"groupIds": [group_one["groupId"]]})
    assert archived_request.status_code == 409

    requested = user_c.post("/api/user-groups/requests", json={"groupIds": [group_two["groupId"]]})
    assert requested.status_code == 200, requested.text
    request_id = requested.json()[0]["requestId"]
    duplicate_pending = user_c.post("/api/user-groups/requests", json={"groupIds": [group_two["groupId"]]})
    assert duplicate_pending.status_code == 200, duplicate_pending.text
    assert duplicate_pending.json() == []
    assert user_c.delete(f"/api/user-groups/requests/{request_id}").status_code == 200
    requested_again = user_c.post("/api/user-groups/requests", json={"groupIds": [group_two["groupId"]]})
    second_request_id = requested_again.json()[0]["requestId"]
    rejected = admin.patch(f"/api/user-groups/requests/{second_request_id}", json={"decision": "rejected"})
    assert rejected.status_code == 200, rejected.text
    statuses = {request["status"] for request in user_c.get("/api/user-groups/me").json()["requests"]}
    assert {"cancelled", "rejected"}.issubset(statuses)


def test_legacy_workspace_migration_creates_group_public_space(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE user_groups (id TEXT PRIMARY KEY, name TEXT, created_by_user_id TEXT, created_at DATETIME)"))
        connection.execute(text("CREATE TABLE user_group_memberships (id TEXT PRIMARY KEY, group_id TEXT, user_id TEXT, created_at DATETIME)"))
        connection.execute(text("CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT, kind TEXT, owner_user_id TEXT, is_read_only BOOLEAN, created_at DATETIME)"))
        connection.execute(text("CREATE TABLE workspace_memberships (id TEXT PRIMARY KEY, workspace_id TEXT, user_id TEXT, role TEXT, created_at DATETIME)"))
        connection.execute(text("CREATE TABLE experiments (id TEXT PRIMARY KEY, workspace_id TEXT, created_by_user_id TEXT)"))
        connection.execute(text("CREATE TABLE reports (id TEXT PRIMARY KEY, experiment_id TEXT, workspace_id TEXT, created_by_user_id TEXT)"))
        connection.execute(text("INSERT INTO users VALUES ('user_a')"))
        connection.execute(text("INSERT INTO users VALUES ('user_b')"))
        connection.execute(text("INSERT INTO user_groups VALUES ('group_a', 'Data Team', 'user_a', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO user_group_memberships VALUES ('ugm_a', 'group_a', 'user_a', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO workspaces VALUES ('ws_private', 'A Personal', 'personal', 'user_a', 0, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO workspaces VALUES ('ws_custom', 'Old Shared', 'shared', 'user_a', 0, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO workspace_memberships VALUES ('wm_a', 'ws_private', 'user_a', 'owner', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO workspace_memberships VALUES ('wm_b', 'ws_custom', 'user_b', 'member', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO experiments VALUES ('exp_legacy', 'ws_private', 'user_a')"))
        connection.execute(text("INSERT INTO reports VALUES ('report_legacy', 'exp_legacy', 'ws_private', 'user_a')"))

    ensure_schema_compatibility(engine)
    with engine.connect() as connection:
        kinds = dict(connection.execute(text("SELECT id, kind FROM workspaces WHERE id IN ('ws_private', 'ws_custom')")).all())
        public = connection.execute(text("SELECT id, group_id FROM workspaces WHERE kind = 'public'")).one()
        manager_role = connection.execute(
            text("SELECT role FROM user_group_memberships WHERE group_id = 'group_a' AND user_id = 'user_a'")
        ).scalar_one()
        public_role = connection.execute(
            text("SELECT role FROM workspace_memberships WHERE workspace_id = :workspace_id AND user_id = 'user_a'"),
            {"workspace_id": public[0]},
        ).scalar_one()
        custom_member = connection.execute(
            text("SELECT role FROM workspace_memberships WHERE workspace_id = 'ws_custom' AND user_id = 'user_b'")
        ).scalar_one()
        legacy_experiment = connection.execute(
            text("SELECT workspace_id, created_by_user_id FROM experiments WHERE id = 'exp_legacy'")
        ).one()
        legacy_report = connection.execute(
            text("SELECT experiment_id, workspace_id FROM reports WHERE id = 'report_legacy'")
        ).one()
    assert kinds == {"ws_private": "private", "ws_custom": "custom"}
    assert public[1] == "group_a"
    assert manager_role == "manager"
    assert public_role == "manager"
    assert custom_member == "member"
    assert tuple(legacy_experiment) == ("ws_private", "user_a")
    assert tuple(legacy_report) == ("exp_legacy", "ws_private")
