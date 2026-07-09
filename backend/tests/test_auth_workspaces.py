from __future__ import annotations

import json
import time
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
from app.services.agent import orchestrator as agent_orchestrator_module


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


def _insert_agent_ready_experiment(session, *, workspace_id: str, user_id: str, experiment_id: str, name: str) -> None:
    history = [
        {"time": f"2024-01-{day:02d}", "value": float(120 + day * 3), "route": "intl" if day % 3 == 0 else "domestic", "price": float(500 + day * 2)}
        for day in range(1, 29)
    ]
    backtest_rows = [
        {
            "time": f"2024-01-{day:02d}",
            "predicted": float(170 + day),
            "actual": float(168 + day * 1.5),
            "residual": round(float((168 + day * 1.5) - (170 + day)), 3),
            "absoluteError": round(abs(float((168 + day * 1.5) - (170 + day))), 3),
            "squaredError": round(float(((168 + day * 1.5) - (170 + day)) ** 2), 3),
        }
        for day in range(22, 29)
    ]
    created_at = datetime.now(timezone.utc)
    explainability = {
        "modelId": "xgboost",
        "modelName": "XGBoost",
        "targetColumn": "value",
        "supported": True,
        "warning": None,
        "featureImportance": [
            {"feature": "lag_7", "importance": 0.42, "rank": 1},
            {"feature": "price", "importance": 0.27, "rank": 2},
            {"feature": "promo_flag", "importance": 0.18, "rank": 3},
        ],
        "shapSupported": True,
        "shapWarning": None,
        "shapTopFeatures": [
            {"feature": "lag_7", "meanAbsShap": 9.2, "rank": 1, "direction": "positive"},
            {"feature": "price", "meanAbsShap": 6.4, "rank": 2, "direction": "negative"},
            {"feature": "promo_flag", "meanAbsShap": 3.1, "rank": 3, "direction": "positive"},
        ],
        "singlePoint": {
            "time": backtest_rows[-1]["time"],
            "actual": backtest_rows[-1]["actual"],
            "predicted": backtest_rows[-1]["predicted"],
            "residual": backtest_rows[-1]["residual"],
            "absoluteError": backtest_rows[-1]["absoluteError"],
            "contributions": [
                {"feature": "lag_7", "value": 181.0, "shapValue": 4.2, "direction": "positive"},
                {"feature": "price", "value": 556.0, "shapValue": -2.8, "direction": "negative"},
            ],
        },
    }
    session.add(
        ExperimentRecord(
            id=experiment_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            name=name,
            file_name="agent_demo.csv",
            sheet_name="CSV",
            target_column="value",
            recommended_model_id="xgboost",
            best_mae="2.1",
            model_count="2",
            config_json=json.dumps(
                {
                    "selectedModels": ["xgboost", "naive"],
                    "featureConfig": {
                        "lagFeatures": True,
                        "rollingFeatures": True,
                        "calendarFeatures": True,
                        "holidayFeatures": False,
                        "covariates": True,
                    },
                    "parameterStrategy": "auto",
                }
            ),
            data_profile_json=json.dumps(
                {
                    "targets": [
                        {
                            "targetColumn": "value",
                            "detectedFrequency": "D",
                            "availableColumns": ["date", "value", "route", "price", "promo_flag", "holiday"],
                            "history": history,
                            "covariateColumns": ["price", "promo_flag", "holiday"],
                            "covariates": [
                                {
                                    "name": "price",
                                    "type": "static",
                                    "backtestStrategy": "repeat_last_known",
                                    "forecastStrategy": "repeat_last_known",
                                    "leakageRisk": False,
                                    "note": "Price is treated as static in v0.4+.",
                                },
                                {
                                    "name": "promo_flag",
                                    "type": "static",
                                    "backtestStrategy": "use_test_values",
                                    "forecastStrategy": "repeat_last_known",
                                    "leakageRisk": True,
                                    "note": "Backtest uses observed promo flag and may be optimistic.",
                                },
                                {
                                    "name": "holiday",
                                    "type": "known_future",
                                    "backtestStrategy": "use_test_timeline",
                                    "forecastStrategy": "calendar",
                                    "leakageRisk": False,
                                    "note": "Calendar-derived future-known covariate.",
                                },
                            ],
                            "warnings": ["covariate strategy demo"],
                        }
                    ]
                }
            ),
            metrics_json=json.dumps(
                [
                    {
                        "modelId": "xgboost",
                        "modelName": "XGBoost",
                        "rank": 1,
                        "metrics": {"mae": 2.1, "rmse": 2.8, "wape": 0.042},
                        "runtime": {"fitSeconds": 1.8, "predictSeconds": 0.2},
                        "status": "success",
                        "warnings": [],
                    },
                    {
                        "modelId": "naive",
                        "modelName": "Naive",
                        "rank": 2,
                        "metrics": {"mae": 2.8, "rmse": 3.4, "wape": 0.051},
                        "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01},
                        "status": "success",
                        "warnings": ["baseline"],
                    },
                ]
            ),
            backtest_json=json.dumps(
                {
                    "actual": [{"time": row["time"], "value": row["actual"]} for row in backtest_rows],
                    "predictions": {
                        "xgboost": backtest_rows,
                        "naive": [
                            {
                                **row,
                                "predicted": round(float(row["predicted"]) + 0.9, 3),
                                "residual": round(float(row["actual"]) - (float(row["predicted"]) + 0.9), 3),
                            }
                            for row in backtest_rows
                        ],
                    },
                }
            ),
            diagnostics_json=json.dumps(
                {
                    "originalRowCount": 28,
                    "validRowCount": 28,
                    "droppedRowCount": 0,
                    "duplicateTimeCount": 0,
                    "missingTimeCount": 0,
                    "invalidTimeCount": 0,
                    "outlierCount": 2,
                    "outlierAdjustedCount": 0,
                    "warnings": ["diagnostic snapshot available"],
                }
            ),
            series_json=json.dumps(history),
            final_forecast_json=json.dumps(
                {
                    "experimentId": experiment_id,
                    "finalModelId": "xgboost",
                    "history": history[-14:],
                    "forecast": [
                        {"time": "2024-01-29", "predicted": 205.0},
                        {"time": "2024-01-30", "predicted": 208.0},
                        {"time": "2024-01-31", "predicted": 211.0},
                    ],
                }
            ),
            model_logs_json=json.dumps(
                [
                    {
                        "modelId": "xgboost",
                        "modelName": "XGBoost",
                        "targetColumn": "value",
                        "status": "success",
                        "metrics": {"mae": 2.1, "rmse": 2.8},
                        "runtime": {"fitSeconds": 1.8, "predictSeconds": 0.2},
                        "warnings": [],
                        "tuning": {
                            "bestMetric": 2.1,
                            "tuningSeconds": 3.2,
                            "selectedParams": {"max_depth": 6, "learning_rate": 0.05},
                        },
                        "explainability": explainability,
                    },
                    {
                        "modelId": "naive",
                        "modelName": "Naive",
                        "targetColumn": "value",
                        "status": "success",
                        "metrics": {"mae": 2.8, "rmse": 3.4},
                        "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01},
                        "warnings": ["baseline"],
                        "tuning": None,
                    },
                ]
            ),
            runtime_json=None,
            manifest_json=json.dumps(
                {
                    "schemaVersion": "0.5.5",
                    "experimentId": experiment_id,
                    "configHash": "agent-demo-hash",
                    "environment": {"appVersion": "test", "platform": "pytest", "device": "cpu"},
                    "data": {
                        "fileName": "agent_demo.csv",
                        "sheetName": "CSV",
                        "columns": ["date", "value", "route", "price", "promo_flag", "holiday"],
                        "timeColumn": "date",
                        "targetColumns": ["value"],
                    },
                }
            ),
            config_hash="agent-demo-hash",
            source_file_sha256="sha-agent-demo",
            app_version="test",
            git_commit=None,
            created_at=created_at,
        )
    )


def _wait_for_agent_status(client: TestClient, *, experiment_id: str, run_id: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.time() + timeout_seconds
    latest = None
    while time.time() < deadline:
        response = client.get(f"/api/experiments/{experiment_id}/agent/runs/{run_id}")
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest["status"] in {"completed", "failed", "cancelled"}:
            return latest
        time.sleep(0.1)
    raise AssertionError(f"Agent run {run_id} did not finish in time. Last payload: {latest}")


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


def test_agent_run_plan_history_and_artifact_replay(isolated_auth_env):
    admin_client = isolated_auth_env.make_client()
    admin_session = _bootstrap_admin(admin_client)
    personal_workspace_id = admin_session["defaultWorkspaceId"]

    db = isolated_auth_env.session_local()
    try:
        _insert_agent_ready_experiment(
            db,
            workspace_id=personal_workspace_id,
            user_id=admin_session["user"]["userId"],
            experiment_id="exp_agent_plan_1",
            name="Agent Planning Demo",
        )
        db.commit()
    finally:
        db.close()

    admin_client.headers.update({"X-Workspace-Id": personal_workspace_id})
    response = admin_client.post(
        "/api/experiments/exp_agent_plan_1/agent/runs",
        json={
            "prompt": "解释这次下降原因，并生成一张管理层可看的瀑布图，再写进报告。",
            "currentPage": "/experiments/exp_agent_plan_1/attribution",
            "currentTab": "attribution",
            "selectedModelId": "xgboost",
            "autoExecute": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "planned"
    skill_ids = [step["skillId"] for step in payload["plan"]]
    assert "read_attribution_snapshot" in skill_ids
    assert "driver_ranking" in skill_ids
    assert "generate_waterfall_chart" in skill_ids
    assert "generate_report_section" in skill_ids

    run_id = payload["runId"]
    detail = admin_client.get(f"/api/experiments/exp_agent_plan_1/agent/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["context"]["experimentId"] == "exp_agent_plan_1"
    assert detail_payload["context"]["workspaceId"] == personal_workspace_id
    assert detail_payload["request"]["prompt"].startswith("解释这次下降原因")
    assert detail_payload["events"][0]["type"] == "plan"
    assert detail_payload["messages"][0]["role"] == "user"
    assert detail_payload["availableSkills"]

    history = admin_client.get("/api/experiments/exp_agent_plan_1/agent/history")
    assert history.status_code == 200, history.text
    history_payload = history.json()
    assert len(history_payload) == 1
    assert history_payload[0]["runId"] == run_id
    assert history_payload[0]["requestPreview"].startswith("解释这次下降原因")

    events = admin_client.get(f"/api/experiments/exp_agent_plan_1/agent/runs/{run_id}/events")
    assert events.status_code == 200, events.text
    assert events.json()["events"][0]["title"] == "Plan created"


def test_agent_auto_execute_generates_artifacts_and_report_record(isolated_auth_env, monkeypatch):
    monkeypatch.setattr(agent_orchestrator_module, "SessionLocal", isolated_auth_env.session_local)
    admin_client = isolated_auth_env.make_client()
    admin_session = _bootstrap_admin(admin_client)
    personal_workspace_id = admin_session["defaultWorkspaceId"]

    db = isolated_auth_env.session_local()
    try:
        _insert_agent_ready_experiment(
            db,
            workspace_id=personal_workspace_id,
            user_id=admin_session["user"]["userId"],
            experiment_id="exp_agent_exec_1",
            name="Agent Execution Demo",
        )
        db.commit()
    finally:
        db.close()

    admin_client.headers.update({"X-Workspace-Id": personal_workspace_id})
    response = admin_client.post(
        "/api/experiments/exp_agent_exec_1/agent/runs",
        json={
            "prompt": "这次最主要的下降原因是什么？生成一张管理层可看的瀑布图，并给我一份完整报告。",
            "currentPage": "/experiments/exp_agent_exec_1",
            "currentTab": "attribution",
            "selectedModelId": "xgboost",
            "autoExecute": True,
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["runId"]

    detail_payload = _wait_for_agent_status(admin_client, experiment_id="exp_agent_exec_1", run_id=run_id)
    assert detail_payload["status"] == "completed"
    assert any(artifact["kind"] == "chart" for artifact in detail_payload["artifacts"])
    assert any(artifact["kind"] == "report" for artifact in detail_payload["artifacts"])
    assert any(message["role"] == "assistant" for message in detail_payload["messages"])

    chart_artifact = next(artifact for artifact in detail_payload["artifacts"] if artifact["kind"] == "chart")
    artifact_response = admin_client.get(f"/api/experiments/exp_agent_exec_1/agent/artifacts/{chart_artifact['artifactId']}")
    assert artifact_response.status_code == 200, artifact_response.text
    assert artifact_response.json()["artifactId"] == chart_artifact["artifactId"]

    db = isolated_auth_env.session_local()
    try:
        report_count = db.scalar(
            select(func.count())
            .select_from(ReportRecord)
            .where(
                ReportRecord.experiment_id == "exp_agent_exec_1",
                ReportRecord.workspace_id == personal_workspace_id,
                ReportRecord.model == "attribution-agent-v0.5.5",
            )
        )
    finally:
        db.close()
    assert report_count == 1


def test_agent_cancel_guardrails_and_workspace_scope(isolated_auth_env, monkeypatch):
    monkeypatch.setattr(agent_orchestrator_module, "SessionLocal", isolated_auth_env.session_local)
    admin_client = isolated_auth_env.make_client()
    admin_session = _bootstrap_admin(admin_client)
    personal_workspace_id = admin_session["defaultWorkspaceId"]
    example_workspace_id = next(workspace["workspaceId"] for workspace in admin_session["workspaces"] if workspace["kind"] == "example")

    other_user = _create_user(admin_client, username="agent_member", display_name="Agent Member")

    db = isolated_auth_env.session_local()
    try:
        _insert_agent_ready_experiment(
            db,
            workspace_id=personal_workspace_id,
            user_id=admin_session["user"]["userId"],
            experiment_id="exp_agent_cancel_1",
            name="Agent Cancel Demo",
        )
        db.commit()
    finally:
        db.close()

    admin_client.headers.update({"X-Workspace-Id": personal_workspace_id})
    create_response = admin_client.post(
        "/api/experiments/exp_agent_cancel_1/agent/runs",
        json={
            "prompt": "解释下降原因、协变量泄漏、runtime阶段、feature工厂、异常、同比、季节性、树shap、回归、敏感性、弹性、benchmark对比、分层、瀑布图、热力图、气泡图、图片、scenario、monte carlo、重跑模型、完整报告。",
            "currentPage": "/forecast",
            "currentTab": "results",
            "selectedModelId": "xgboost",
            "autoExecute": True,
        },
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json()["runId"]

    cancel_response = admin_client.post(f"/api/experiments/exp_agent_cancel_1/agent/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200, cancel_response.text
    cancelled = _wait_for_agent_status(admin_client, experiment_id="exp_agent_cancel_1", run_id=run_id)
    assert cancelled["status"] == "cancelled"
    assert any("停止" in message["content"] for message in cancelled["messages"] if message["role"] == "assistant")

    example_client = isolated_auth_env.make_client()
    _login(example_client, username="admin", password="password123", workspace_id=example_workspace_id)
    example_experiment_id = example_client.get("/api/experiments").json()[0]["experimentId"]
    read_only_response = example_client.post(
        f"/api/experiments/{example_experiment_id}/agent/runs",
        json={"prompt": "帮我解释一下这个示例实验。", "currentPage": "/experiments/demo", "autoExecute": False},
    )
    assert read_only_response.status_code == 403

    member_client = isolated_auth_env.make_client()
    member_session = _login(member_client, username="agent_member", password="password123")
    member_client.headers.update({"X-Workspace-Id": member_session["defaultWorkspaceId"]})
    forbidden = member_client.get(f"/api/experiments/exp_agent_cancel_1/agent/runs/{run_id}")
    assert forbidden.status_code == 403
