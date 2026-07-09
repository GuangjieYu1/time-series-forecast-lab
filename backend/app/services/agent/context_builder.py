from __future__ import annotations

import json
from typing import Any

from app.db.models import ExperimentRecord, ReportRecord
from app.schemas import AgentContextSnapshot, AgentRunRequest
from app.services.attribution_snapshot import load_attribution_snapshot
from app.services.runtime_history import load_runtime_from_record


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def build_agent_context(
    *,
    record: ExperimentRecord,
    request: AgentRunRequest,
    workspace_name: str | None = None,
    reports: list[ReportRecord] | None = None,
) -> AgentContextSnapshot:
    data_profile = _loads(record.data_profile_json, {})
    runtime = load_runtime_from_record(record)
    attribution = load_attribution_snapshot(record)
    columns = _extract_available_columns(data_profile)
    covariates = runtime.featurePipeline[0].covariates if runtime and runtime.featurePipeline else []
    report_names = [f"{report.id} · {report.model}" for report in (reports or [])]
    warnings = list(attribution.warnings)
    if request.currentPage == "/forecast" and not record.final_forecast_json:
        warnings.append("当前实验还没有最终预测结果，因此 scenario / Monte Carlo 会以 backtest 误差为主。")
    return AgentContextSnapshot(
        experimentId=record.id,
        experimentName=record.name,
        workspaceId=record.workspace_id,
        workspaceName=workspace_name,
        currentPage=request.currentPage,
        currentTab=request.currentTab,
        targetColumn=record.target_column,
        recommendedModelId=record.recommended_model_id,
        selectedModelId=request.selectedModelId,
        selectedFeatureId=request.selectedFeatureId,
        selectedArtifactId=request.selectedArtifactId,
        selectedVisualId=request.selectedVisualId,
        selectedAnomalyTime=request.selectedAnomalyTime,
        availableColumns=columns,
        covariates=covariates,
        reports=report_names,
        warnings=warnings,
    )


def _extract_available_columns(data_profile: dict[str, Any]) -> list[str]:
    targets = data_profile.get("targets")
    if not isinstance(targets, list) or not targets:
        return []
    first = targets[0] if isinstance(targets[0], dict) else {}
    columns = first.get("availableColumns")
    if isinstance(columns, list):
        return [str(item) for item in columns if item]
    history = first.get("history")
    if isinstance(history, list) and history:
        row = history[0]
        if isinstance(row, dict):
            return [str(key) for key in row.keys()]
    return []
