from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, ExperimentRecord, ReportRecord, UserRecord, WorkspaceMembershipRecord, WorkspaceRecord
from app.db.session import get_db
from app.main import app


@dataclass
class IsolatedAuthEnv:
    session_local: sessionmaker

    def make_client(self) -> TestClient:
        return TestClient(app)


def _manifest_payload(experiment_id: str) -> str:
    return json.dumps(
        {
            "schemaVersion": "0.4",
            "experimentId": experiment_id,
            "experimentName": f"Experiment {experiment_id}",
            "configHash": "hash",
            "sourceFileSha256": "sha",
            "environment": {
                "appVersion": "test",
                "pythonVersion": "3.11",
                "platform": "pytest",
                "device": "cpu",
            },
            "data": {
                "fileName": "demo.csv",
                "fileSize": 1,
                "fileSha256": "sha",
                "sheetName": "CSV",
                "columns": ["date", "value"],
                "timeColumn": "date",
                "targetColumns": ["value"],
            },
            "configuration": {},
        }
    )


def _insert_experiment(session, *, workspace_id: str, user_id: str, experiment_id: str, name: str) -> None:
    session.add(
        ExperimentRecord(
            id=experiment_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            name=name,
            file_name="demo.csv",
            sheet_name="CSV",
            target_column="value",
            recommended_model_id="naive",
            best_mae="1.2",
            model_count="1",
            config_json="{}",
            data_profile_json=json.dumps({"targets": []}),
            metrics_json="[]",
            backtest_json=json.dumps({"actual": [], "predictions": {}}),
            diagnostics_json=json.dumps(
                {
                    "originalRowCount": 10,
                    "validRowCount": 10,
                    "droppedRowCount": 0,
                    "duplicateTimeCount": 0,
                    "missingTimeCount": 0,
                    "invalidTimeCount": 0,
                    "warnings": [],
                }
            ),
            series_json="[]",
            final_forecast_json=None,
            model_logs_json="[]",
            runtime_json=None,
            manifest_json=_manifest_payload(experiment_id),
            config_hash="hash",
            source_file_sha256="sha",
            app_version="test",
            git_commit=None,
            created_at=datetime.now(timezone.utc),
        )
    )


def _insert_report(session, *, report_id: str, experiment_id: str, workspace_id: str, user_id: str) -> None:
    session.add(
        ReportRecord(
            id=report_id,
            experiment_id=experiment_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            content_markdown="# Report\n\nShared scope test.",
            model="deepseek-v4-flash",
            created_at=datetime.now(timezone.utc),
        )
    )


def _login(client: TestClient, *, username: str, password: str, workspace_id: str | None = None):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    if workspace_id:
        client.headers.update({"X-Workspace-Id": workspace_id})
    return response.json()


def _bootstrap_admin(client: TestClient):
    response = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "displayName": "Admin", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _register(client: TestClient, *, username: str, display_name: str, password: str = "password123"):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "displayName": display_name, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_user(client: TestClient, *, username: str, display_name: str, password: str = "password123", is_admin: bool = False):
    response = client.post(
        "/api/users",
        json={"username": username, "displayName": display_name, "password": password, "isAdmin": is_admin},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def isolated_auth_env(tmp_path: Path):
    database_path = tmp_path / "auth.sqlite"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield IsolatedAuthEnv(session_local=TestingSessionLocal)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_bootstrap_login_logout_and_repeat_bootstrap_rejected(isolated_auth_env):
    client = isolated_auth_env.make_client()

    me_before = client.get("/api/auth/me")
    assert me_before.status_code == 200
    assert me_before.json()["bootstrapRequired"] is True
    assert me_before.json()["authenticated"] is False

    bootstrapped = _bootstrap_admin(client)
    assert bootstrapped["authenticated"] is True
    assert bootstrapped["user"]["isAdmin"] is True
    assert any(workspace["kind"] == "personal" for workspace in bootstrapped["workspaces"])
    assert any(workspace["kind"] == "example" for workspace in bootstrapped["workspaces"])

    repeated = isolated_auth_env.make_client().post(
        "/api/auth/bootstrap",
        json={"username": "another", "displayName": "Another", "password": "password123"},
    )
    assert repeated.status_code == 409

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    me_after_logout = client.get("/api/auth/me").json()
    assert me_after_logout["authenticated"] is False
    assert me_after_logout["bootstrapRequired"] is False

    bad_login = isolated_auth_env.make_client().post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad_login.status_code == 401

    relogin_client = isolated_auth_env.make_client()
    logged_in = _login(relogin_client, username="admin", password="password123")
    assert logged_in["authenticated"] is True

    invalid_cookie_client = isolated_auth_env.make_client()
    invalid_cookie_client.cookies.set("tsfl_session", "not-a-real-session")
    assert invalid_cookie_client.get("/api/auth/me").json()["authenticated"] is False


def test_register_requires_bootstrap_then_creates_normal_user(isolated_auth_env):
    pre_bootstrap_client = isolated_auth_env.make_client()
    pre_bootstrap_register = pre_bootstrap_client.post(
        "/api/auth/register",
        json={"username": "analyst", "displayName": "Analyst", "password": "password123"},
    )
    assert pre_bootstrap_register.status_code == 409

    admin_client = isolated_auth_env.make_client()
    _bootstrap_admin(admin_client)

    analyst_client = isolated_auth_env.make_client()
    registered = _register(analyst_client, username="analyst", display_name="Analyst")
    assert registered["authenticated"] is True
    assert registered["user"]["isAdmin"] is False
    workspace_kinds = {workspace["kind"] for workspace in registered["workspaces"]}
    assert {"personal", "example"}.issubset(workspace_kinds)

    duplicate = isolated_auth_env.make_client().post(
        "/api/auth/register",
        json={"username": "analyst", "displayName": "Analyst Again", "password": "password123"},
    )
    assert duplicate.status_code == 409


def test_username_availability_is_public_and_reports_available_taken_invalid(isolated_auth_env):
    client = isolated_auth_env.make_client()

    invalid = client.get("/api/auth/username-availability", params={"username": "ab"})
    assert invalid.status_code == 200
    assert invalid.json() == {
        "available": False,
        "normalizedUsername": "ab",
        "reason": "invalid",
        "message": "用户名需为 3-120 个字符。",
    }

    _bootstrap_admin(client)

    taken = isolated_auth_env.make_client().get("/api/auth/username-availability", params={"username": "admin"})
    assert taken.status_code == 200
    assert taken.json()["available"] is False
    assert taken.json()["reason"] == "taken"
    assert taken.json()["normalizedUsername"] == "admin"

    available = isolated_auth_env.make_client().get("/api/auth/username-availability", params={"username": "fresh_user"})
    assert available.status_code == 200
    assert available.json() == {
        "available": True,
        "normalizedUsername": "fresh_user",
        "reason": "available",
        "message": None,
    }


def test_register_requires_letter_and_number_password_but_admin_flows_keep_old_rule(isolated_auth_env):
    admin_client = isolated_auth_env.make_client()
    _bootstrap_admin(admin_client)

    weak_letters = isolated_auth_env.make_client().post(
        "/api/auth/register",
        json={"username": "letters_only", "displayName": "Letters Only", "password": "abcdefgh"},
    )
    assert weak_letters.status_code == 400
    assert weak_letters.json().get("detail", weak_letters.json())["code"] == "WEAK_PASSWORD"

    weak_digits = isolated_auth_env.make_client().post(
        "/api/auth/register",
        json={"username": "digits_only", "displayName": "Digits Only", "password": "12345678"},
    )
    assert weak_digits.status_code == 400
    assert weak_digits.json().get("detail", weak_digits.json())["code"] == "WEAK_PASSWORD"

    admin_created = _create_user(admin_client, username="legacy_user", display_name="Legacy User", password="abcdefgh")
    legacy_client = isolated_auth_env.make_client()
    legacy_session = _login(legacy_client, username="legacy_user", password="abcdefgh")
    assert legacy_session["authenticated"] is True

    reset_password = admin_client.patch(
        f"/api/users/{admin_created['userId']}/password",
        json={"password": "87654321"},
    )
    assert reset_password.status_code == 200, reset_password.text

    relogin_after_reset = _login(isolated_auth_env.make_client(), username="legacy_user", password="87654321")
    assert relogin_after_reset["authenticated"] is True


def test_admin_created_user_gets_personal_workspace(isolated_auth_env):
    admin_client = isolated_auth_env.make_client()
    _bootstrap_admin(admin_client)

    created_user = _create_user(admin_client, username="analyst", display_name="Analyst")

    db = isolated_auth_env.session_local()
    try:
        personal_count = db.scalar(
            select(func.count())
            .select_from(WorkspaceRecord)
            .where(WorkspaceRecord.owner_user_id == created_user["userId"], WorkspaceRecord.kind == "personal")
        )
        example_membership_count = db.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipRecord)
            .join(WorkspaceRecord, WorkspaceRecord.id == WorkspaceMembershipRecord.workspace_id)
            .where(
                WorkspaceMembershipRecord.user_id == created_user["userId"],
                WorkspaceRecord.kind == "example",
            )
        )
    finally:
        db.close()

    assert personal_count == 1
    assert example_membership_count == 1

    analyst_client = isolated_auth_env.make_client()
    session = _login(analyst_client, username="analyst", password="password123")
    workspace_kinds = {workspace["kind"] for workspace in session["workspaces"]}
    assert {"personal", "example"}.issubset(workspace_kinds)


def test_shared_workspace_membership_and_member_permissions(isolated_auth_env):
    admin_client = isolated_auth_env.make_client()
    admin_session = _bootstrap_admin(admin_client)
    member = _create_user(admin_client, username="member", display_name="Member")

    created_workspace = admin_client.post("/api/workspaces", json={"name": "Revenue Squad"})
    assert created_workspace.status_code == 200, created_workspace.text
    shared_workspace_id = created_workspace.json()["workspaceId"]

    add_member = admin_client.post(
        f"/api/workspaces/{shared_workspace_id}/members",
        headers={"X-Workspace-Id": shared_workspace_id},
        json={"userId": member["userId"]},
    )
    assert add_member.status_code == 200, add_member.text

    member_client = isolated_auth_env.make_client()
    member_session = _login(member_client, username="member", password="password123", workspace_id=shared_workspace_id)
    member_workspace_ids = {workspace["workspaceId"] for workspace in member_session["workspaces"]}
    assert shared_workspace_id in member_workspace_ids

    members_response = member_client.get(f"/api/workspaces/{shared_workspace_id}/members")
    assert members_response.status_code == 200
    assert len(members_response.json()) == 2

    forbidden_add = member_client.post(f"/api/workspaces/{shared_workspace_id}/members", json={"userId": admin_session["user"]["userId"]})
    assert forbidden_add.status_code == 403

    forbidden_remove = member_client.delete(f"/api/workspaces/{shared_workspace_id}/members/{admin_session['user']['userId']}")
    assert forbidden_remove.status_code == 403

    remove_member = admin_client.delete(
        f"/api/workspaces/{shared_workspace_id}/members/{member['userId']}",
        headers={"X-Workspace-Id": shared_workspace_id},
    )
    assert remove_member.status_code == 200


def test_workspace_scoping_upload_ownership_and_example_read_only(isolated_auth_env, generated_fixtures: Path):
    admin_client = isolated_auth_env.make_client()
    admin_session = _bootstrap_admin(admin_client)
    admin_personal_id = admin_session["defaultWorkspaceId"]
    example_workspace_id = next(workspace["workspaceId"] for workspace in admin_session["workspaces"] if workspace["kind"] == "example")

    member = _create_user(admin_client, username="member", display_name="Member")
    shared_workspace = admin_client.post("/api/workspaces", json={"name": "Ops Shared"}).json()
    shared_workspace_id = shared_workspace["workspaceId"]
    admin_client.post(
        f"/api/workspaces/{shared_workspace_id}/members",
        headers={"X-Workspace-Id": shared_workspace_id},
        json={"userId": member["userId"]},
    )

    db = isolated_auth_env.session_local()
    try:
        personal_experiment_id = "exp_personal_1"
        shared_experiment_id = "exp_shared_1"
        _insert_experiment(db, workspace_id=admin_personal_id, user_id=admin_session["user"]["userId"], experiment_id=personal_experiment_id, name="Personal experiment")
        _insert_experiment(db, workspace_id=shared_workspace_id, user_id=admin_session["user"]["userId"], experiment_id=shared_experiment_id, name="Shared experiment")
        _insert_report(db, report_id="report_personal_1", experiment_id=personal_experiment_id, workspace_id=admin_personal_id, user_id=admin_session["user"]["userId"])
        db.commit()
    finally:
        db.close()

    member_client = isolated_auth_env.make_client()
    _login(member_client, username="member", password="password123", workspace_id=shared_workspace_id)

    experiment_list = member_client.get("/api/experiments")
    assert experiment_list.status_code == 200
    ids = {item["experimentId"] for item in experiment_list.json()}
    assert shared_experiment_id in ids
    assert personal_experiment_id not in ids

    assert member_client.get(f"/api/experiments/{personal_experiment_id}").status_code == 403
    assert member_client.get(f"/api/experiments/{personal_experiment_id}/manifest").status_code == 403
    assert member_client.delete(f"/api/experiments/{personal_experiment_id}").status_code == 403
    assert member_client.get(f"/api/runtime/{personal_experiment_id}").status_code == 403
    assert member_client.post(f"/api/reports/report_personal_1/pdf", json={"title": "x", "visualArtifacts": []}).status_code == 403

    fixture = generated_fixtures / "daily_air_passengers.csv"
    with fixture.open("rb") as handle:
        upload_response = admin_client.post("/api/upload/preview", headers={"X-Workspace-Id": admin_personal_id}, files={"file": (fixture.name, handle, "text/csv")})
    assert upload_response.status_code == 200, upload_response.text
    upload_body = upload_response.json()
    upload_id = upload_body["uploadId"]

    cross_user_preview = member_client.get(f"/api/upload/{upload_id}/sheets/CSV/preview")
    assert cross_user_preview.status_code == 403

    cross_workspace_preview = admin_client.get(
        f"/api/upload/{upload_id}/sheets/CSV/preview",
        headers={"X-Workspace-Id": shared_workspace_id},
    )
    assert cross_workspace_preview.status_code == 403

    with fixture.open("rb") as handle:
        read_only_upload = admin_client.post(
            "/api/upload/preview",
            headers={"X-Workspace-Id": example_workspace_id},
            files={"file": (fixture.name, handle, "text/csv")},
        )
    assert read_only_upload.status_code == 403
