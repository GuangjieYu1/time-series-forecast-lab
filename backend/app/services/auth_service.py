from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.core.constants import APP_VERSION
from app.core.security import password_hash, utc_now
from app.db.models import (
    ExperimentRecord,
    ReportRecord,
    SessionRecord,
    UserRecord,
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from app.schemas import WorkspaceSummary
from app.services.report_pdf import build_report_pdf


EXAMPLE_WORKSPACE_NAME = "Codex walkthrough current UI"


@dataclass
class UserProvisionResult:
    user: UserRecord
    personal_workspace: WorkspaceRecord


def serialize_json(value) -> str:
    return json.dumps(value, ensure_ascii=True)


def count_users(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(UserRecord)) or 0)


def get_user_by_username(db: Session, username: str) -> UserRecord | None:
    return db.scalar(select(UserRecord).where(UserRecord.username == username))


def create_user_with_personal_workspace(
    db: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    is_admin: bool,
) -> UserProvisionResult:
    now = utc_now()
    user = UserRecord(
        id=f"user_{uuid.uuid4().hex[:12]}",
        username=username.strip(),
        display_name=display_name.strip() or username.strip(),
        password_hash=password_hash(password),
        is_admin=is_admin,
        is_active=True,
        created_at=now,
    )
    db.add(user)
    db.flush()

    personal_workspace = WorkspaceRecord(
        id=f"ws_{uuid.uuid4().hex[:12]}",
        name=f"{user.display_name} · Personal",
        kind="personal",
        owner_user_id=user.id,
        is_read_only=False,
        created_at=now,
    )
    db.add(personal_workspace)
    db.flush()
    db.add(
        WorkspaceMembershipRecord(
            id=f"wm_{uuid.uuid4().hex[:12]}",
            workspace_id=personal_workspace.id,
            user_id=user.id,
            role="owner",
            created_at=now,
        )
    )
    _grant_example_workspace_memberships(db, user.id, created_at=now)
    return UserProvisionResult(user=user, personal_workspace=personal_workspace)


def _grant_example_workspace_memberships(db: Session, user_id: str, *, created_at: datetime | None = None) -> None:
    now = created_at or utc_now()
    example_ids = db.scalars(select(WorkspaceRecord.id).where(WorkspaceRecord.kind == "example")).all()
    for workspace_id in example_ids:
        exists = db.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipRecord)
            .where(WorkspaceMembershipRecord.workspace_id == workspace_id, WorkspaceMembershipRecord.user_id == user_id)
        )
        if exists:
            continue
        db.add(
            WorkspaceMembershipRecord(
                id=f"wm_{uuid.uuid4().hex[:12]}",
                workspace_id=workspace_id,
                user_id=user_id,
                role="member",
                created_at=now,
            )
        )


def list_workspace_memberships_query(user_id: str) -> Select[tuple[WorkspaceMembershipRecord, WorkspaceRecord]]:
    return (
        select(WorkspaceMembershipRecord, WorkspaceRecord)
        .join(WorkspaceRecord, WorkspaceRecord.id == WorkspaceMembershipRecord.workspace_id)
        .where(WorkspaceMembershipRecord.user_id == user_id)
        .order_by(
            WorkspaceRecord.kind.asc(),
            WorkspaceRecord.created_at.asc(),
        )
    )


def list_workspace_summaries(db: Session, user: UserRecord) -> list[WorkspaceSummary]:
    rows = db.execute(list_workspace_memberships_query(user.id)).all()
    summaries = [
        WorkspaceSummary(
            workspaceId=workspace.id,
            name=workspace.name,
            kind=workspace.kind,
            role=membership.role,
            isReadOnly=workspace.is_read_only,
            ownerUserId=workspace.owner_user_id,
            isPersonal=workspace.kind == "personal",
            isOwner=membership.role == "owner",
            createdAt=workspace.created_at.isoformat(),
        )
        for membership, workspace in rows
    ]
    summaries.sort(key=lambda item: (0 if item.kind == "personal" else 1 if item.kind == "shared" else 2, item.name.lower()))
    return summaries


def default_workspace_id(workspaces: list[WorkspaceSummary]) -> str | None:
    if not workspaces:
        return None
    for workspace in workspaces:
        if workspace.kind == "personal":
            return workspace.workspaceId
    return workspaces[0].workspaceId


def delete_workspace_and_contents(db: Session, workspace: WorkspaceRecord) -> None:
    experiment_ids = db.scalars(select(ExperimentRecord.id).where(ExperimentRecord.workspace_id == workspace.id)).all()
    if experiment_ids:
        db.execute(delete(ReportRecord).where(ReportRecord.experiment_id.in_(experiment_ids)))
    db.execute(delete(ReportRecord).where(ReportRecord.workspace_id == workspace.id))
    db.execute(delete(ExperimentRecord).where(ExperimentRecord.workspace_id == workspace.id))
    db.execute(delete(WorkspaceMembershipRecord).where(WorkspaceMembershipRecord.workspace_id == workspace.id))
    db.delete(workspace)


def seed_example_workspace(db: Session, *, owner_user_id: str, backend_root: Path) -> WorkspaceRecord:
    existing = db.scalar(select(WorkspaceRecord).where(WorkspaceRecord.kind == "example"))
    if existing is not None:
        return existing

    now = utc_now()
    workspace = WorkspaceRecord(
        id=f"ws_{uuid.uuid4().hex[:12]}",
        name=EXAMPLE_WORKSPACE_NAME,
        kind="example",
        owner_user_id=owner_user_id,
        is_read_only=True,
        created_at=now,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMembershipRecord(
            id=f"wm_{uuid.uuid4().hex[:12]}",
            workspace_id=workspace.id,
            user_id=owner_user_id,
            role="owner",
            created_at=now,
        )
    )
    _seed_example_artifacts(db, workspace_id=workspace.id, owner_user_id=owner_user_id, backend_root=backend_root, now=now)
    return workspace


def _seed_example_artifacts(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    backend_root: Path,
    now: datetime,
) -> None:
    fixture_path = backend_root / "tests" / "fixtures" / "daily_air_passengers.csv"
    if not fixture_path.exists():
        return
    frame = pd.read_csv(fixture_path)
    value_col = "passenger_count"
    time_col = "date"
    history = [{"time": str(row[time_col]), "value": float(row[value_col])} for _, row in frame.iterrows()]
    horizon = 7
    train = frame.iloc[:-horizon]
    test = frame.iloc[-horizon:]
    preds = []
    rolling_window = 7
    history_values = train[value_col].tolist()
    for idx, (_, row) in enumerate(test.iterrows()):
        predicted = float(history_values[-1 if idx == 0 else -1])
        actual = float(row[value_col])
        residual = actual - predicted
        preds.append(
            {
                "time": str(row[time_col]),
                "predicted": round(predicted, 3),
                "actual": round(actual, 3),
                "residual": round(residual, 3),
                "absoluteError": round(abs(residual), 3),
                "squaredError": round(residual * residual, 3),
            }
        )
        history_values.append(actual)
    mae = round(sum(item["absoluteError"] for item in preds) / len(preds), 3) if preds else 0.0
    mse = round(sum(item["squaredError"] for item in preds) / len(preds), 3) if preds else 0.0
    rmse = round(math.sqrt(mse), 3) if preds else 0.0
    total_actual = sum(float(item["actual"]) for item in preds) or 1.0
    wape = round(sum(float(item["absoluteError"]) for item in preds) / total_actual, 4)
    example_id = f"exp_example_{uuid.uuid4().hex[:8]}"
    manifest = {
        "schemaVersion": "0.4",
        "experimentId": example_id,
        "experimentName": "Codex walkthrough current UI · Example",
        "createdAt": now.isoformat(),
        "configHash": "example-config-hash",
        "sourceFileSha256": "example-sha256",
        "datasetHash": "example-sha256",
        "featurePipelineVersion": "0.4",
        "runtimeEventSchemaVersion": "0.4",
        "randomSeed": 42,
        "environment": {
            "appVersion": APP_VERSION,
            "gitCommit": None,
            "pythonVersion": "seeded",
            "platform": "local",
            "device": "cpu",
            "memoryTotalMb": None,
            "memoryAvailableMb": None,
            "modelCapabilityVersions": None,
            "packageVersions": {},
        },
        "data": {
            "fileName": fixture_path.name,
            "fileSize": int(fixture_path.stat().st_size),
            "fileSha256": "example-sha256",
            "sheetName": "CSV",
            "columns": list(frame.columns),
            "timeColumn": time_col,
            "targetColumns": [value_col],
            "covariateColumns": [],
        },
        "configuration": {
            "sheetName": "CSV",
            "timeColumn": time_col,
            "targetColumns": [value_col],
            "selectedModels": ["naive", "moving_average"],
            "featureConfig": {
                "lagFeatures": True,
                "rollingFeatures": True,
                "calendarFeatures": True,
                "holidayFeatures": False,
                "covariates": False,
            },
            "horizon": horizon,
            "testSize": horizon,
            "parameterStrategy": "default",
            "runProfile": "balanced",
        },
        "featurePipelines": [],
        "targets": [
            {
                "targetColumn": value_col,
                "detectedFrequency": "D",
                "timeStart": history[0]["time"] if history else None,
                "timeEnd": history[-1]["time"] if history else None,
                "trainStart": str(train.iloc[0][time_col]) if not train.empty else None,
                "trainEnd": str(train.iloc[-1][time_col]) if not train.empty else None,
                "testStart": str(test.iloc[0][time_col]) if not test.empty else None,
                "testEnd": str(test.iloc[-1][time_col]) if not test.empty else None,
                "recommendedModelId": "naive",
                "models": [
                    {
                        "modelId": "naive",
                        "modelName": "Naive",
                        "status": "success",
                        "metrics": {"mae": mae, "mse": mse, "rmse": rmse, "wape": wape},
                        "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01},
                        "warnings": [],
                        "error": None,
                        "tuning": None,
                    }
                ],
            }
        ],
    }
    experiment = ExperimentRecord(
        id=example_id,
        workspace_id=workspace_id,
        created_by_user_id=owner_user_id,
        name="Codex walkthrough current UI · Example",
        file_name=fixture_path.name,
        sheet_name="CSV",
        target_column=value_col,
        recommended_model_id="naive",
        best_mae=str(mae),
        model_count="2",
        config_json=serialize_json(manifest["configuration"]),
        data_profile_json=serialize_json(
            {
                "targets": [
                    {
                        "targetColumn": value_col,
                        "detectedFrequency": "D",
                        "sourceFrequency": "D",
                        "history": history,
                        "futureCovariates": [],
                        "covariateHistory": [],
                        "covariateConfigs": [],
                        "holidayConfig": {"enabled": False, "countryCode": "CN", "observed": True, "windowDays": 1},
                        "warnings": ["Example workspace is read-only."],
                    }
                ]
            }
        ),
        metrics_json=serialize_json(
            [
                {
                    "modelId": "naive",
                    "modelName": "Naive",
                    "rank": 1,
                    "metrics": {"mae": mae, "mse": mse, "rmse": rmse, "wape": wape},
                    "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01},
                    "status": "success",
                    "warnings": [],
                    "error": None,
                    "tuning": None,
                },
                {
                    "modelId": "moving_average",
                    "modelName": "Moving Average",
                    "rank": 2,
                    "metrics": {"mae": round(mae * 1.08, 3), "mse": round(mse * 1.1, 3), "rmse": round(rmse * 1.05, 3), "wape": round(wape * 1.08, 4)},
                    "runtime": {"fitSeconds": 0.02, "predictSeconds": 0.01},
                    "status": "success",
                    "warnings": ["Example comparison model."],
                    "error": None,
                    "tuning": None,
                },
            ]
        ),
        backtest_json=serialize_json(
            {
                "actual": [{"time": item["time"], "value": item["actual"]} for item in preds],
                "predictions": {"naive": preds},
            }
        ),
        diagnostics_json=serialize_json(
            {
                "originalRowCount": int(len(frame)),
                "validRowCount": int(len(frame)),
                "droppedRowCount": 0,
                "duplicateTimeCount": 0,
                "missingTimeCount": 0,
                "invalidTimeCount": 0,
                "inputMissingTargetCount": 0,
                "invalidTargetCount": 0,
                "filledValueCount": 0,
                "outlierCount": 0,
                "outlierAdjustedCount": 0,
                "cleaningActions": ["Example experiment seeded from fixture dataset."],
                "timeStart": history[0]["time"] if history else None,
                "timeEnd": history[-1]["time"] if history else None,
                "warnings": ["Example workspace is read-only and intended for walkthrough only."],
            }
        ),
        series_json=serialize_json(history),
        final_forecast_json=serialize_json(
            {
                "experimentId": example_id,
                "finalModelId": "naive",
                "history": history[-30:],
                "forecast": [],
                "modelInfo": {"name": "Naive", "supportsPredictionInterval": False},
            }
        ),
        model_logs_json=serialize_json(
            [
                {"targetColumn": value_col, "modelId": "naive", "status": "success", "warnings": [], "error": None, "runtime": {"fitSeconds": 0.01, "predictSeconds": 0.01}, "tuning": None},
                {"targetColumn": value_col, "modelId": "moving_average", "status": "success", "warnings": ["Example comparison model."], "error": None, "runtime": {"fitSeconds": 0.02, "predictSeconds": 0.01}, "tuning": None},
            ]
        ),
        runtime_json=None,
        manifest_json=serialize_json(manifest),
        config_hash="example-config-hash",
        source_file_sha256="example-sha256",
        app_version=APP_VERSION,
        git_commit=None,
        created_at=now,
    )
    db.add(experiment)
    report_content = (
        "# Codex walkthrough current UI\n\n"
        "这是一个随系统初始化自动生成的 Example 工作区，用来演示当前 UI 与实验结果展示方式。\n\n"
        "## 你可以在这里看到什么\n\n"
        "- 实验历史、排行榜、回测结果和残差入口\n"
        "- Feature Factory / Runtime / 报告导出链路\n"
        "- 只读空间行为：可查看、不可修改、不可删除\n\n"
        "## 数据与模型\n\n"
        f"- 数据集：`{fixture_path.name}`\n"
        f"- 目标列：`{value_col}`\n"
        "- 推荐模型：Naive\n"
        f"- Example MAE：{mae}\n\n"
        "## 说明\n\n"
        "这个示例报告对应的 PDF 支持复制文本与搜索文本；如果你下载 PDF，图像说明与总结也会保留为真实文本。"
    )
    report = ReportRecord(
        id=f"report_example_{uuid.uuid4().hex[:8]}",
        experiment_id=example_id,
        workspace_id=workspace_id,
        created_by_user_id=owner_user_id,
        content_markdown=report_content,
        model="deepseek-v4-flash",
        created_at=now + timedelta(seconds=1),
    )
    db.add(report)
    pdf_path = backend_root / "data" / "example_report.pdf"
    try:
        pdf_path.write_bytes(build_report_pdf(title="Codex walkthrough current UI", content_markdown=report_content, visual_artifacts=[]))
    except Exception:
        pass
