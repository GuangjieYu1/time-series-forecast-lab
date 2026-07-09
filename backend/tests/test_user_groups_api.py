from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def isolated_client(tmp_path):
    database_path = tmp_path / "user-groups.sqlite"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
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
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _bootstrap_admin(client: TestClient):
    response = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "displayName": "Admin", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_admin_can_create_assign_and_delete_user_groups(isolated_client: TestClient):
    _bootstrap_admin(isolated_client)

    created_user = isolated_client.post(
        "/api/users",
        json={"username": "analyst", "displayName": "Analyst", "password": "password123", "isAdmin": False},
    )
    assert created_user.status_code == 200, created_user.text
    user_id = created_user.json()["userId"]

    data_group = isolated_client.post(
        "/api/user-groups",
        json={"name": "Data Team", "description": "分析和报表"},
    )
    assert data_group.status_code == 200, data_group.text
    data_group_id = data_group.json()["groupId"]

    ops_group = isolated_client.post(
        "/api/user-groups",
        json={"name": "Ops Team", "description": "运维和值班"},
    )
    assert ops_group.status_code == 200, ops_group.text
    ops_group_id = ops_group.json()["groupId"]

    assigned = isolated_client.put(
        f"/api/users/{user_id}/groups",
        json={"groupIds": [data_group_id, ops_group_id]},
    )
    assert assigned.status_code == 200, assigned.text
    assert [group["groupId"] for group in assigned.json()["groups"]] == [data_group_id, ops_group_id]

    listed_users = isolated_client.get("/api/users")
    assert listed_users.status_code == 200, listed_users.text
    analyst = next(user for user in listed_users.json() if user["userId"] == user_id)
    assert [group["name"] for group in analyst["groups"]] == ["Data Team", "Ops Team"]

    listed_groups = isolated_client.get("/api/user-groups")
    assert listed_groups.status_code == 200, listed_groups.text
    group_counts = {group["name"]: group["memberCount"] for group in listed_groups.json()}
    assert group_counts == {"Data Team": 1, "Ops Team": 1}

    deleted = isolated_client.delete(f"/api/user-groups/{data_group_id}")
    assert deleted.status_code == 200, deleted.text

    refreshed_groups = isolated_client.get("/api/user-groups")
    assert refreshed_groups.status_code == 200, refreshed_groups.text
    assert [group["name"] for group in refreshed_groups.json()] == ["Ops Team"]
    assert refreshed_groups.json()[0]["memberCount"] == 1

    refreshed_users = isolated_client.get("/api/users")
    assert refreshed_users.status_code == 200, refreshed_users.text
    analyst_after_delete = next(user for user in refreshed_users.json() if user["userId"] == user_id)
    assert analyst_after_delete["groups"] == [{"groupId": ops_group_id, "name": "Ops Team"}]
