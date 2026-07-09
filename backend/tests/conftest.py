from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import password_hash, utc_now
from app.db.models import UserRecord, WorkspaceMembershipRecord, WorkspaceRecord
from app.db.session import SessionLocal
from app.main import app
from app.services.auth_service import create_user_with_personal_workspace, seed_example_workspace
from tests.generate_fixtures import ensure_fixtures


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session", autouse=True)
def generated_fixtures() -> Path:
    ensure_fixtures()
    return Path(__file__).resolve().parent / "fixtures"


TEST_USERNAME = "pytest_admin"
TEST_PASSWORD = "pytest_admin_password"
TEST_DISPLAY_NAME = "Pytest Admin"


@dataclass
class AuthenticatedClient:
    client: TestClient
    user_id: str
    workspace_id: str


def ensure_test_admin_user() -> tuple[str, str]:
    db = SessionLocal()
    try:
        user = db.scalar(select(UserRecord).where(UserRecord.username == TEST_USERNAME))
        if user is None:
            created = create_user_with_personal_workspace(
                db,
                username=TEST_USERNAME,
                display_name=TEST_DISPLAY_NAME,
                password=TEST_PASSWORD,
                is_admin=True,
            )
            seed_example_workspace(db, owner_user_id=created.user.id, backend_root=get_settings().backend_dir)
            db.commit()
            return created.user.id, created.personal_workspace.id

        user.display_name = TEST_DISPLAY_NAME
        user.password_hash = password_hash(TEST_PASSWORD)
        user.is_admin = True
        user.is_active = True
        workspace_id = db.scalar(
            select(WorkspaceRecord.id).where(
                WorkspaceRecord.owner_user_id == user.id,
                WorkspaceRecord.kind == "personal",
            )
        )
        if workspace_id is None:
            now = utc_now()
            workspace = WorkspaceRecord(
                id=f"ws_{uuid.uuid4().hex[:12]}",
                name=f"{TEST_DISPLAY_NAME} · Personal",
                kind="personal",
                owner_user_id=user.id,
                is_read_only=False,
                created_at=now,
            )
            db.add(workspace)
            db.flush()
            db.add(
                WorkspaceMembershipRecord(
                    id=f"wm_{uuid.uuid4().hex[:12]}",
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="owner",
                    created_at=now,
                )
            )
            seed_example_workspace(db, owner_user_id=user.id, backend_root=get_settings().backend_dir)
            db.commit()
            return user.id, workspace.id
        db.commit()
        return user.id, workspace_id
    finally:
        db.close()


@pytest.fixture()
def authed_client() -> AuthenticatedClient:
    user_id, workspace_id = ensure_test_admin_user()
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    client.headers.update({"X-Workspace-Id": workspace_id})
    return AuthenticatedClient(client=client, user_id=user_id, workspace_id=workspace_id)
