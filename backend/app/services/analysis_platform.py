from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.constants import APP_VERSION
from app.core.errors import AppError
from app.core.storage import read_upload_metadata, save_generated_upload_bytes
from app.db.models import ExperimentRecord
from app.schemas import (
    AgentDatasetContext,
    AgentDecisionCard,
    AnalysisAgentPlanStep,
    AnalysisAgentResponse,
    AgentArtifact,
    AttributionSnapshot,
    AttributionSnapshotSection,
    DatasetColumnProfile,
    DatasetIssue,
    DatasetProfile,
    DatasetRecommendation,
    DatasetTransformPlan,
    DatasetTransformResult,
    ReadinessDimensionScore,
    ReadinessScore,
    RouteSuggestion,
    WorkflowStageDetail,
    WorkflowRouteSuggestion,
    WorkflowRunDetail,
)
from app.services.file_parser import preview_sheet, preview_upload, read_sheet_dataframe
from app.services.schema_profiler import infer_column_type


_TIME_NAME_RE = re.compile(r"(date|time|month|year|quarter|week|day|日期|时间|月份|年月|季度)", re.IGNORECASE)
_ID_NAME_RE = re.compile(r"(id|code|uuid|编号|单号|流水号|route_id|user_id|订单号)", re.IGNORECASE)


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _series_preview_values(series: pd.Series, limit: int = 5) -> list[Any]:
    values: list[Any] = []
    for item in series.head(max(limit * 3, limit)):
        if pd.isna(item):
            continue
        normalized = item.isoformat() if hasattr(item, "isoformat") else item
        if normalized not in values:
            values.append(normalized)
        if len(values) >= limit:
            break
    return values


def _is_time_candidate(name: str, inferred_type: str) -> bool:
    return inferred_type == "datetime" or bool(_TIME_NAME_RE.search(name))


def _is_identifier_candidate(name: str, inferred_type: str, unique_rate: float, non_null_count: int) -> bool:
    if non_null_count < 8 or inferred_type == "datetime":
        return False
    if _ID_NAME_RE.search(name):
        return True
    return inferred_type in {"string", "boolean"} and unique_rate >= 0.95


def _dimension(key: str, label: str, score: float, reason: str) -> ReadinessDimensionScore:
    return ReadinessDimensionScore(key=key, label=label, score=max(0, min(int(round(score)), 100)), reason=reason)


def build_dataset_profile(upload_id: str, sheet_name: str, *, workspace_id: str | None = None) -> DatasetProfile:
    metadata = read_upload_metadata(upload_id)
    df = read_sheet_dataframe(upload_id, sheet_name)
    return build_dataset_profile_from_dataframe(
        df,
        upload_id=upload_id,
        file_name=metadata["fileName"],
        sheet_name=sheet_name,
        workspace_id=workspace_id,
    )


def build_dataset_profile_from_dataframe(
    df: pd.DataFrame,
    *,
    upload_id: str,
    file_name: str,
    sheet_name: str,
    workspace_id: str | None = None,
) -> DatasetProfile:
    normalized = df.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    preview_rows = normalized.head(100).to_dict(orient="records")
    row_count = int(len(normalized))
    column_names = [str(column) for column in normalized.columns]
    type_counts: dict[str, int] = {}
    profiles: list[DatasetColumnProfile] = []
    time_candidates: list[str] = []
    target_candidates: list[str] = []
    grouping_candidates: list[str] = []
    numeric_columns: list[str] = []
    categorical_columns: list[str] = []
    text_columns: list[str] = []
    issues: list[DatasetIssue] = []

    for column in column_names:
        series = normalized[column]
        preview_values = series.head(100).tolist()
        inferred_type = infer_column_type(preview_values, column)
        type_counts[inferred_type] = type_counts.get(inferred_type, 0) + 1

        non_null_count = int(series.notna().sum())
        null_count = max(row_count - non_null_count, 0)
        null_rate = (null_count / row_count) if row_count else 0.0
        unique_count = int(series.dropna().astype(str).nunique()) if non_null_count else 0
        unique_rate = (unique_count / non_null_count) if non_null_count else 0.0
        is_constant = non_null_count > 0 and unique_count <= 1
        is_identifier = _is_identifier_candidate(column, inferred_type, unique_rate, non_null_count)

        numeric_mean = None
        numeric_std = None
        role_hints: list[str] = []
        if inferred_type == "number":
            numeric_columns.append(column)
            numeric_series = pd.to_numeric(series, errors="coerce").dropna()
            if not numeric_series.empty:
                numeric_mean = float(numeric_series.mean())
                numeric_std = float(numeric_series.std(ddof=0)) if len(numeric_series) > 1 else 0.0
            if not is_constant and not is_identifier and null_rate < 0.65:
                target_candidates.append(column)
                role_hints.append("target_candidate")
            if not is_identifier:
                role_hints.append("feature_candidate")
        elif inferred_type in {"string", "boolean"}:
            cardinality_ceiling = min(50, max(3, int(max(row_count, 1) * 0.3)))
            if 1 < unique_count <= cardinality_ceiling:
                grouping_candidates.append(column)
                categorical_columns.append(column)
                role_hints.append("grouping_candidate")
            else:
                text_columns.append(column)

        if _is_time_candidate(column, inferred_type):
            time_candidates.append(column)
            role_hints.append("time_candidate")
        if is_identifier:
            role_hints.append("identifier_candidate")
        if is_constant:
            role_hints.append("constant_candidate")

        profiles.append(
            DatasetColumnProfile(
                name=column,
                inferredType=inferred_type,
                sampleValues=_series_preview_values(series),
                nonNullCountInPreview=min(non_null_count, 100),
                nullCountInPreview=max(min(null_count, 100), 0),
                uniqueCountInPreview=min(unique_count, 100),
                uniqueRateInPreview=round(unique_rate, 4),
                nullRateInPreview=round(null_rate, 4),
                isConstant=is_constant,
                isPotentialIdentifier=is_identifier,
                numericMeanInPreview=numeric_mean,
                numericStdInPreview=numeric_std,
                roleHints=role_hints,
            )
        )

        if is_constant:
            issues.append(
                DatasetIssue(
                    issueType="constant_column",
                    severity="high",
                    title=f"{column} 是常量列",
                    description="这一列几乎不提供区分能力，保留会增加噪音或导致聚类/建模偏移。",
                    columns=[column],
                    metricValue=1.0,
                )
            )
        if null_rate >= 0.4:
            issues.append(
                DatasetIssue(
                    issueType="high_missing_rate",
                    severity="warn" if null_rate < 0.7 else "high",
                    title=f"{column} 缺失率偏高",
                    description=f"当前列缺失率约为 {null_rate:.0%}，建议先决定是否删除、填补或改成弱特征。",
                    columns=[column],
                    metricValue=round(null_rate, 4),
                )
            )
        if is_identifier:
            issues.append(
                DatasetIssue(
                    issueType="suspected_identifier",
                    severity="warn",
                    title=f"{column} 疑似标识列",
                    description="高唯一值或 ID 命名通常不适合直接进模型，容易带来伪模式和泄漏风险。",
                    columns=[column],
                    metricValue=round(unique_rate, 4),
                )
            )

    duplicate_rows = int(normalized.duplicated().sum()) if row_count else 0
    if duplicate_rows:
        issues.append(
            DatasetIssue(
                issueType="duplicate_rows",
                severity="warn",
                title="发现重复行",
                description=f"检测到 {duplicate_rows} 行完全重复记录，建议确认是否属于重复采集或导入错误。",
                metricValue=float(duplicate_rows),
            )
        )

    if time_candidates:
        time_column = time_candidates[0]
        duplicate_time_count = int(normalized[time_column].duplicated().sum())
        if duplicate_time_count:
            issues.append(
                DatasetIssue(
                    issueType="duplicate_time_index",
                    severity="high",
                    title=f"{time_column} 存在重复时间索引",
                    description="同一个时间点出现多条记录时，预测工作流和时序回测通常需要先聚合或补充分组列。",
                    columns=[time_column],
                    metricValue=float(duplicate_time_count),
                )
            )

    if target_candidates:
        issues.append(
            DatasetIssue(
                issueType="possible_target_candidates",
                severity="info",
                title="发现可作为目标列的候选",
                description="这些数值列可直接进入预测、监督学习或归因分析流程。",
                columns=target_candidates[:8],
                metricValue=float(len(target_candidates)),
            )
        )
    if grouping_candidates:
        issues.append(
            DatasetIssue(
                issueType="possible_grouping_columns",
                severity="info",
                title="发现可作为分组 / 切片维度的候选",
                description="这些列适合做分层归因、聚类切片或业务下钻。",
                columns=grouping_candidates[:8],
                metricValue=float(len(grouping_candidates)),
            )
        )

    recommendations = _build_recommendations(
        profiles=profiles,
        time_candidates=time_candidates,
        target_candidates=target_candidates,
        grouping_candidates=grouping_candidates,
        duplicate_rows=duplicate_rows,
    )
    readiness = _build_readiness_score(
        row_count=row_count,
        profiles=profiles,
        time_candidates=time_candidates,
        target_candidates=target_candidates,
        grouping_candidates=grouping_candidates,
        duplicate_rows=duplicate_rows,
    )

    return DatasetProfile(
        uploadId=upload_id,
        workspaceId=workspace_id,
        fileName=file_name,
        sheetName=sheet_name,
        rowCountApprox=row_count,
        columnCount=len(column_names),
        previewRowCount=min(row_count, 100),
        columns=profiles,
        typeCounts=type_counts,
        timeColumnCandidates=time_candidates,
        targetCandidates=target_candidates,
        groupingCandidates=grouping_candidates,
        numericColumns=numeric_columns,
        categoricalColumns=categorical_columns,
        textColumns=text_columns,
        issues=issues,
        recommendations=recommendations,
        readinessScore=readiness,
    )


def suggest_routes(profile: DatasetProfile) -> RouteSuggestion:
    usable_feature_count = sum(
        1
        for column in profile.columns
        if not column.isConstant and not column.isPotentialIdentifier and column.inferredType in {"number", "string", "boolean"}
    )
    route_rows: list[WorkflowRouteSuggestion] = []

    forecast_score = 20
    forecast_reasons: list[str] = []
    forecast_required: list[str] = []
    forecast_warnings: list[str] = []
    if profile.timeColumnCandidates:
        forecast_score += 35
        forecast_reasons.append(f"检测到时间列候选：{profile.timeColumnCandidates[0]}")
    else:
        forecast_required.append("至少选择一个时间列")
        forecast_warnings.append("没有时间列时，不建议直接进入时间序列预测。")
    if profile.targetCandidates:
        forecast_score += 30
        forecast_reasons.append(f"检测到连续目标列候选：{profile.targetCandidates[0]}")
    else:
        forecast_required.append("选择一个连续数值目标列")
    if any(issue.issueType == "duplicate_time_index" for issue in profile.issues):
        forecast_score -= 20
        forecast_warnings.append("时间索引存在重复，预测前建议先聚合或补充分组字段。")
    route_rows.append(
        WorkflowRouteSuggestion(
            analysisType="forecast",
            label="时间序列预测",
            eligible=bool(profile.timeColumnCandidates and profile.targetCandidates),
            matchScore=max(0, min(forecast_score, 100)),
            reasons=forecast_reasons or ["需要时间列和目标列后再进入预测 workflow。"],
            requiredInputs=forecast_required,
            warnings=forecast_warnings,
            nextPath="/forecast",
        )
    )

    attribution_score = 25 + min(len(profile.targetCandidates), 2) * 20 + min(len(profile.groupingCandidates), 3) * 10
    attribution_eligible = bool(profile.targetCandidates and (len(profile.groupingCandidates) + usable_feature_count >= 3))
    route_rows.append(
        WorkflowRouteSuggestion(
            analysisType="attribution",
            label="归因分析",
            eligible=attribution_eligible,
            matchScore=max(0, min(attribution_score, 100)),
            reasons=[
                "存在可解释的业务指标候选。",
                "同时具备分组维度或解释特征，适合做 driver ranking / 切片下钻。",
            ],
            requiredInputs=[] if profile.targetCandidates else ["选择一个要解释的业务指标列"],
            warnings=["如果目标列是金额 / 数量，请先确认聚合粒度一致。"] if attribution_eligible else ["需要目标列和解释维度后再进入归因 workflow。"],
            nextPath=None,
        )
    )

    supervised_score = 20 + min(len(profile.targetCandidates), 2) * 25 + min(usable_feature_count, 6) * 6
    supervised_eligible = bool(profile.targetCandidates and usable_feature_count >= 3)
    route_rows.append(
        WorkflowRouteSuggestion(
            analysisType="supervised_ml",
            label="监督学习",
            eligible=supervised_eligible,
            matchScore=max(0, min(supervised_score, 100)),
            reasons=[
                "存在可作为标签的目标列候选。",
                f"当前可用特征约 {usable_feature_count} 个，足够进入经典 tabular workflow。"
            ],
            requiredInputs=[] if profile.targetCandidates else ["选择一个标签列 / 目标列"],
            warnings=["第一版默认优先跑回归式 tabular baseline。"] if supervised_eligible else ["需要目标列和至少 3 个可用特征后再进入监督学习 workflow。"],
            nextPath=None,
        )
    )

    cluster_feature_count = len([column for column in profile.columns if column.inferredType == "number" and not column.isConstant and not column.isPotentialIdentifier])
    clustering_score = 15 + min(cluster_feature_count, 8) * 9
    clustering_eligible = cluster_feature_count >= 2
    route_rows.append(
        WorkflowRouteSuggestion(
            analysisType="clustering",
            label="聚类分析",
            eligible=clustering_eligible,
            matchScore=max(0, min(clustering_score, 100)),
            reasons=[f"当前可聚类数值特征约 {cluster_feature_count} 个。"],
            requiredInputs=[] if clustering_eligible else ["至少选择 2 个可聚类数值特征"],
            warnings=["聚类结果依赖标准化与特征选择，建议先查看数据画像。"] if clustering_eligible else ["数值特征不足时，聚类结论通常不稳定。"],
            nextPath=None,
        )
    )

    route_rows.sort(key=lambda item: item.matchScore, reverse=True)
    if route_rows:
        route_rows[0].recommended = route_rows[0].eligible

    return RouteSuggestion(
        recommendedRoutes=[item for item in route_rows if item.eligible],
        blockedRoutes=[item for item in route_rows if not item.eligible],
        requiredInputs=sorted({value for item in route_rows for value in item.requiredInputs}),
        reasoning=[f"{item.label} 匹配度 {item.matchScore}%：{'；'.join(item.reasons[:2])}" for item in route_rows],
        warnings=[warning for item in route_rows for warning in item.warnings[:1]],
    )


def plan_transform(
    upload_id: str,
    sheet_name: str,
    transform_type: str,
    columns: list[str],
    *,
    workspace_id: str | None = None,
) -> DatasetTransformPlan:
    metadata = read_upload_metadata(upload_id)
    before_df = read_sheet_dataframe(upload_id, sheet_name)
    before_profile = build_dataset_profile_from_dataframe(before_df, upload_id=upload_id, file_name=metadata["fileName"], sheet_name=sheet_name, workspace_id=workspace_id)
    transformed_df, applied_columns = _apply_transform(before_df, before_profile, transform_type, columns)
    after_profile = build_dataset_profile_from_dataframe(
        transformed_df,
        upload_id=upload_id,
        file_name=metadata["fileName"],
        sheet_name=sheet_name,
        workspace_id=workspace_id,
    )
    delta = after_profile.readinessScore.overall - before_profile.readinessScore.overall
    explanation = _transform_explanation(transform_type, applied_columns, before_profile, delta)
    return DatasetTransformPlan(
        transformType=transform_type,
        explanation=explanation,
        columns=applied_columns,
        willCreateNewDataset=True,
        readinessBefore=before_profile.readinessScore,
        readinessAfter=after_profile.readinessScore,
        datasetIssuesAddressed=[issue.title for issue in before_profile.issues if set(issue.columns) & set(applied_columns)],
        expectedEffects=[
            f"Readiness Score 预计变化 {delta:+d} 分。",
            f"处理后字段数 {after_profile.columnCount}，当前有效特征候选 {len(after_profile.numericColumns) + len(after_profile.categoricalColumns)} 个。",
        ],
    )


def execute_transform(
    upload_id: str,
    sheet_name: str,
    transform_type: str,
    columns: list[str],
    *,
    user_id: str,
    workspace_id: str,
) -> DatasetTransformResult:
    metadata = read_upload_metadata(upload_id)
    before_df = read_sheet_dataframe(upload_id, sheet_name)
    before_profile = build_dataset_profile_from_dataframe(before_df, upload_id=upload_id, file_name=metadata["fileName"], sheet_name=sheet_name, workspace_id=workspace_id)
    transformed_df, applied_columns = _apply_transform(before_df, before_profile, transform_type, columns)
    generated_name = f"{metadata['fileName'].rsplit('.', 1)[0]}__{transform_type}.csv"
    generated_bytes = transformed_df.to_csv(index=False).encode("utf-8-sig")
    saved = save_generated_upload_bytes(file_name=generated_name, content=generated_bytes, user_id=user_id, workspace_id=workspace_id)
    preview = preview_upload(saved["uploadId"], limit=100)
    sheet = preview.sheets[0]
    after_profile = build_dataset_profile(saved["uploadId"], sheet.sheetName, workspace_id=workspace_id)
    delta = after_profile.readinessScore.overall - before_profile.readinessScore.overall
    return DatasetTransformResult(
        transformType=transform_type,
        appliedColumns=applied_columns,
        upload=preview,
        sheet=sheet,
        datasetProfile=after_profile,
        readinessBefore=before_profile.readinessScore,
        readinessAfter=after_profile.readinessScore,
        qualityDeltaSummary=f"Readiness Score 从 {before_profile.readinessScore.overall} 提升到 {after_profile.readinessScore.overall}（{delta:+d}）。",
        beforeIssues=before_profile.issues,
        afterIssues=after_profile.issues,
    )


def start_analysis_workflow(
    analysis_type: str,
    *,
    upload_id: str,
    sheet_name: str,
    experiment_name: str | None,
    target_column: str | None,
    time_column: str | None,
    grouping_columns: list[str],
    feature_columns: list[str],
    cluster_count: int | None,
    workspace_id: str,
    created_by_user_id: str,
    db: Session,
) -> WorkflowRunDetail:
    metadata = read_upload_metadata(upload_id)
    profile = build_dataset_profile(upload_id, sheet_name, workspace_id=workspace_id)
    run_id = f"analysis_{uuid.uuid4().hex[:10]}"

    if analysis_type == "forecast":
        return WorkflowRunDetail(
            runId=run_id,
            status="completed",
            analysisType="forecast",
            experimentId=None,
            experimentName=experiment_name or f"{metadata['fileName']} · Forecast",
            nextPath="/forecast",
            summary="已完成 route 上下文预判，下一步进入 Forecast workflow 继续选择时间列、目标列和模型。",
            warnings=[] if profile.timeColumnCandidates else ["当前数据尚未检测到明显时间列，进入预测页后请手动确认字段映射。"],
            currentStage="handoff",
            progressPercent=100,
            startedAt=_utc_now(),
            completedAt=_utc_now(),
            configSummary={
                "timeColumn": time_column or (profile.timeColumnCandidates[0] if profile.timeColumnCandidates else None),
                "targetColumn": target_column or (profile.targetCandidates[0] if profile.targetCandidates else None),
            },
            metricsSummary={"recommendedRouteScore": next((route.matchScore for route in suggest_routes(profile).recommendedRoutes if route.analysisType == "forecast"), 0)},
            stages=[
                WorkflowStageDetail(
                    stageId="handoff",
                    title="进入 Forecast Workflow",
                    description="已完成 route 选择，下一步跳转到预测工作流页。",
                    status="completed",
                    progressPercent=100,
                )
            ],
        )

    experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
    if analysis_type == "attribution":
        experiment_payload = _build_attribution_experiment_payload(
            experiment_id=experiment_id,
            profile=profile,
            target_column=target_column,
            grouping_columns=grouping_columns,
            upload_id=upload_id,
            sheet_name=sheet_name,
        )
    elif analysis_type == "supervised_ml":
        experiment_payload = _build_supervised_experiment_payload(
            experiment_id=experiment_id,
            profile=profile,
            target_column=target_column,
            feature_columns=feature_columns,
            upload_id=upload_id,
            sheet_name=sheet_name,
        )
    elif analysis_type == "clustering":
        experiment_payload = _build_clustering_experiment_payload(
            experiment_id=experiment_id,
            profile=profile,
            feature_columns=feature_columns,
            cluster_count=cluster_count,
            upload_id=upload_id,
            sheet_name=sheet_name,
        )
    else:
        raise AppError("Unsupported analysis workflow.", code="ANALYSIS_WORKFLOW_UNSUPPORTED")

    record = ExperimentRecord(
        id=experiment_id,
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        name=experiment_name or experiment_payload["experimentName"],
        analysis_type=analysis_type,
        parent_upload_id=upload_id,
        source_experiment_id=None,
        file_name=metadata["fileName"],
        sheet_name=sheet_name,
        target_column=experiment_payload["targetColumn"],
        recommended_model_id=experiment_payload.get("recommendedModelId"),
        best_mae=str(experiment_payload["bestMae"]) if experiment_payload.get("bestMae") is not None else None,
        model_count=str(experiment_payload.get("modelCount", 0)),
        config_json=_safe_json(experiment_payload.get("config", {})),
        data_profile_json=_safe_json({"analysisType": analysis_type, "timeColumn": time_column, "availableColumns": [column.name for column in profile.columns]}),
        dataset_profile_json=_safe_json(profile.model_dump(mode="json")),
        metrics_json=_safe_json(experiment_payload.get("metrics", [])),
        backtest_json=_safe_json(experiment_payload.get("backtest", {})),
        diagnostics_json=_safe_json(experiment_payload.get("diagnostics", {})),
        series_json=_safe_json(experiment_payload.get("series", [])),
        final_forecast_json=None,
        model_logs_json=_safe_json(experiment_payload.get("modelLogs", [])),
        runtime_json=None,
        attribution_json=_safe_json(experiment_payload.get("attribution")) if experiment_payload.get("attribution") else None,
        manifest_json=None,
        workflow_state_json=_safe_json(experiment_payload.get("workflowState", {})),
        artifacts_json=_safe_json([artifact.model_dump(mode="json") for artifact in experiment_payload.get("artifacts", [])]),
        config_hash=None,
        source_file_sha256=metadata["fileSha256"],
        app_version=APP_VERSION,
        git_commit=None,
    )
    db.add(record)
    db.commit()
    config_summary = {
        "targetColumn": experiment_payload["targetColumn"],
        "timeColumn": time_column,
        "groupingColumns": grouping_columns,
        "featureColumns": experiment_payload.get("config", {}).get("featureColumns", feature_columns),
        "clusterCount": experiment_payload.get("config", {}).get("clusterCount", cluster_count),
    }
    metrics_summary = (experiment_payload.get("metrics") or [{}])[0].get("metrics", {})
    return WorkflowRunDetail(
        runId=run_id,
        status="running",
        analysisType=analysis_type,
        experimentId=experiment_id,
        experimentName=record.name,
        nextPath=f"/experiments/{experiment_id}",
        summary=experiment_payload["summary"],
        warnings=experiment_payload.get("warnings", []),
        currentStage="profile_dataset",
        progressPercent=8,
        startedAt=_utc_now(),
        completedAt=None,
        configSummary=config_summary,
        metricsSummary=metrics_summary,
        stages=_stage_blueprints_for_analysis(analysis_type),
        rerunSupported=True,
    )


def _build_recommendations(
    *,
    profiles: list[DatasetColumnProfile],
    time_candidates: list[str],
    target_candidates: list[str],
    grouping_candidates: list[str],
    duplicate_rows: int,
) -> list[DatasetRecommendation]:
    items: list[DatasetRecommendation] = []
    constant_columns = [column.name for column in profiles if column.isConstant]
    if constant_columns:
        items.append(
            DatasetRecommendation(
                recommendationId="drop_constants",
                title="删除常量列",
                description="常量列几乎不提供信息增益，先移除会让后续建模和聚类更稳定。",
                actionType="drop_constant_columns",
                columns=constant_columns,
                expectedBenefit="减少噪音，提高 Feature Usability。",
            )
        )
    id_columns = [column.name for column in profiles if column.isPotentialIdentifier]
    if id_columns:
        items.append(
            DatasetRecommendation(
                recommendationId="drop_identifiers",
                title="检查或删除疑似 ID 列",
                description="高唯一标识列容易制造伪规律，归因和监督学习都建议先排除。",
                actionType="drop_identifier_columns",
                columns=id_columns,
                expectedBenefit="降低泄漏风险，提升模型泛化性。",
            )
        )
    if time_candidates:
        items.append(
            DatasetRecommendation(
                recommendationId="confirm_time_column",
                title="确认时间字段",
                description=f"系统已经识别到时间列候选 {time_candidates[0]}，进入预测 workflow 时建议优先选择它。",
                actionType="routing",
                columns=time_candidates[:1],
                expectedBenefit="提升 Temporal Integrity，减少预测配置错误。",
            )
        )
    if target_candidates:
        items.append(
            DatasetRecommendation(
                recommendationId="choose_target_column",
                title="确认分析目标",
                description=f"当前可作为业务指标 / 标签的候选包括：{'、'.join(target_candidates[:4])}。",
                actionType="routing",
                columns=target_candidates[:4],
                expectedBenefit="明确任务后，可直接进入预测、监督学习或归因分析。",
            )
        )
    if grouping_candidates:
        items.append(
            DatasetRecommendation(
                recommendationId="use_grouping_columns",
                title="保留可下钻维度",
                description="这些列适合做分层归因、业务切片或聚类解释。",
                actionType="routing",
                columns=grouping_candidates[:5],
                expectedBenefit="增强归因和聚类结果的可解释性。",
            )
        )
    if duplicate_rows:
        items.append(
            DatasetRecommendation(
                recommendationId="review_duplicates",
                title="复核重复行来源",
                description="重复记录可能来自多次导入、重复采集或业务口径问题，建议先判定是否去重。",
                actionType="observation",
                columns=[],
                expectedBenefit="减少统计偏差，提升 Completeness 与 Stability。",
            )
        )
    return items


def _build_readiness_score(
    *,
    row_count: int,
    profiles: list[DatasetColumnProfile],
    time_candidates: list[str],
    target_candidates: list[str],
    grouping_candidates: list[str],
    duplicate_rows: int,
) -> ReadinessScore:
    if not profiles:
        dimensions = [
            _dimension("completeness", "Completeness", 0, "还没有可分析的字段。"),
            _dimension("stability", "Stability", 0, "数据为空。"),
            _dimension("temporal_integrity", "Temporal Integrity", 0, "无法判断时间结构。"),
            _dimension("feature_usability", "Feature Usability", 0, "没有可用特征。"),
            _dimension("leakage_risk", "Leakage Risk", 0, "无法评估泄漏风险。"),
            _dimension("modeling_readiness", "Modeling Readiness", 0, "无法进入任何 workflow。"),
        ]
        return ReadinessScore(overall=0, level="poor", dimensions=dimensions, summary="当前数据为空，暂时无法开始分析。")

    avg_null_rate = float(sum(column.nullRateInPreview for column in profiles) / max(len(profiles), 1))
    constant_count = sum(1 for column in profiles if column.isConstant)
    id_count = sum(1 for column in profiles if column.isPotentialIdentifier)
    usable_features = sum(
        1
        for column in profiles
        if not column.isConstant and not column.isPotentialIdentifier and column.inferredType in {"number", "string", "boolean"}
    )
    completeness = 100 - avg_null_rate * 120
    stability = 100 - constant_count * 10 - min(duplicate_rows / max(row_count, 1), 1) * 35
    temporal = 35 + (35 if time_candidates else 0) + (10 if not duplicate_rows else 0) + (20 if row_count >= 12 else 5)
    feature_usability = min(100, 25 + usable_features * 9 - constant_count * 4)
    leakage_risk = max(10, 100 - id_count * 15 - constant_count * 3)
    modeling = min(
        100,
        15
        + (25 if target_candidates else 0)
        + (20 if time_candidates else 0)
        + min(usable_features * 4, 20)
        + (10 if grouping_candidates else 0),
    )
    dimensions = [
        _dimension("completeness", "Completeness", completeness, f"平均缺失率约 {avg_null_rate:.0%}。"),
        _dimension("stability", "Stability", stability, f"常量列 {constant_count} 个，重复行 {duplicate_rows} 个。"),
        _dimension("temporal_integrity", "Temporal Integrity", temporal, "是否具备稳定时间索引与连续结构。"),
        _dimension("feature_usability", "Feature Usability", feature_usability, f"当前可用特征约 {usable_features} 个。"),
        _dimension("leakage_risk", "Leakage Risk", leakage_risk, f"疑似 ID / 泄漏风险列 {id_count} 个。"),
        _dimension("modeling_readiness", "Modeling Readiness", modeling, "综合判断是否适合直接进入 workflow。"),
    ]
    overall = int(round(sum(item.score for item in dimensions) / len(dimensions)))
    if overall >= 85:
        level = "excellent"
    elif overall >= 70:
        level = "good"
    elif overall >= 55:
        level = "fair"
    else:
        level = "poor"
    return ReadinessScore(
        overall=overall,
        level=level,
        dimensions=dimensions,
        summary=f"当前数据整体 readiness 为 {overall}/100，最适合先做 {'时间序列预测' if time_candidates and target_candidates else '归因 / 监督学习探索'}。",
    )


def _apply_transform(
    df: pd.DataFrame,
    profile: DatasetProfile,
    transform_type: str,
    columns: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    transformed = df.copy()
    if transform_type == "drop_constant_columns":
        applied = columns or [column.name for column in profile.columns if column.isConstant]
        return transformed.drop(columns=[column for column in applied if column in transformed.columns]), applied
    if transform_type == "drop_identifier_columns":
        applied = columns or [column.name for column in profile.columns if column.isPotentialIdentifier]
        return transformed.drop(columns=[column for column in applied if column in transformed.columns]), applied
    if transform_type == "drop_high_missing_columns":
        applied = columns or [column.name for column in profile.columns if column.nullRateInPreview >= 0.4]
        return transformed.drop(columns=[column for column in applied if column in transformed.columns]), applied
    if transform_type == "normalize_numeric_features":
        applied = columns or [column.name for column in profile.columns if column.inferredType == "number" and not column.isPotentialIdentifier]
        for column in applied:
            if column not in transformed.columns:
                continue
            numeric = pd.to_numeric(transformed[column], errors="coerce")
            mean = numeric.mean()
            std = numeric.std(ddof=0)
            if pd.isna(std) or float(std) == 0:
                continue
            transformed[column] = (numeric - mean) / std
        return transformed, applied
    raise AppError("Unsupported dataset transform.", code="TRANSFORM_UNSUPPORTED")


def _transform_explanation(transform_type: str, applied_columns: list[str], profile: DatasetProfile, delta: int) -> str:
    if transform_type == "drop_constant_columns":
        return f"检测到 {len(applied_columns)} 个常量列。删除后可以减少无效特征，让下游 benchmark 和建模更稳定，预计 readiness {delta:+d}。"
    if transform_type == "drop_identifier_columns":
        return f"这些列更像标识符而不是业务驱动因素。先移除能降低泄漏风险，避免模型记住记录 ID，预计 readiness {delta:+d}。"
    if transform_type == "drop_high_missing_columns":
        return f"高缺失列会拉低 Completeness 与 Feature Usability。先剔除再决定是否单独补回，预计 readiness {delta:+d}。"
    if transform_type == "normalize_numeric_features":
        return f"数值标准化会让聚类距离和线性模型系数更稳定，适合进入 clustering / supervised ML 基础流程，预计 readiness {delta:+d}。"
    return f"将处理 {len(applied_columns)} 列，预计 readiness {delta:+d}。"


def _decision_card_story(
    *,
    action_type: str,
    action_id: str,
    columns: list[str],
    expected_benefit: str,
    route: WorkflowRouteSuggestion | None = None,
    explanation: str = "",
) -> tuple[str, str, str, str]:
    preview_columns = "、".join(columns[:4]) if columns else "当前数据结构"
    if action_type == "transform":
        if action_id == "drop_constant_columns":
            return (
                f"检测到这些列在预览区间内几乎没有变化：{preview_columns}。",
                "常量列不会提供真实区分信息，只会占掉特征位，让下游 benchmark 和建模步骤更容易被噪音拖累。",
                "如果先保留它们，后面的特征工程和模型训练会继续把这些无效列带进去，解释性和稳定性都会变差。",
                expected_benefit or "执行后会减少无效特征，提高 Feature Usability。",
            )
        if action_id == "drop_identifier_columns":
            return (
                f"这些列的唯一值比例很高，更像标识符而不是业务驱动因素：{preview_columns}。",
                "ID 型字段容易让模型记住样本而不是学习规律，也会污染聚类距离和归因解释。",
                "如果不先处理，后续 workflow 很容易出现伪规律或泄漏风险，尤其是在监督学习和聚类里。",
                expected_benefit or "执行后会降低泄漏风险，提高泛化稳定性。",
            )
        if action_id == "drop_high_missing_columns":
            return (
                f"这些列缺失比例偏高：{preview_columns}。",
                "先把高缺失列单独拿出来，能让主流程先建立在更干净的字段集上，再决定哪些值得补回。",
                "如果直接带着高缺失列进入 workflow，Completeness 和 Feature Usability 会持续偏低。",
                expected_benefit or "执行后会让字段集更完整，减少缺失导致的偏差。",
            )
        if action_id == "normalize_numeric_features":
            return (
                f"这些数值列量纲差异明显，建议在聚类或线性建模前先统一尺度：{preview_columns}。",
                "标准化后，距离型算法和系数型模型不会被大数值列天然主导，结果更可比。",
                "如果跳过这一步，聚类中心和线性系数更容易被量纲劫持，难以解释真实业务差异。",
                expected_benefit or "执行后会提升 clustering / supervised ML 的稳定性。",
            )
    if action_type == "workflow" and route is not None:
        return (
            route.reasons[0] if route.reasons else explanation or f"当前数据已经具备进入 {route.label} workflow 的基本条件。",
            "进入 workflow 后，你可以继续手动配置目标列、特征列、簇数或分组方式，同时实时观察每个阶段。",
            "如果暂时不进入这条 workflow，你也可以先处理上面的数据质量问题，再回来复跑比较前后差异。",
            expected_benefit or "进入后可以继续配置、观察和复跑。",
        )
    return (
        explanation or "我先根据当前数据画像整理出一个观察点。",
        "这个动作本身不会直接改数据，但会帮助后续 workflow 或手动判断更稳。",
        "如果略过这一步，后续配置时更容易带着隐性问题直接往下跑。",
        expected_benefit or "先看清问题，再决定是否执行具体变换或 workflow。",
    )


def analyze_dataset_with_agent(
    *,
    upload_id: str,
    sheet_name: str,
    prompt: str,
    current_page: str | None = None,
    selected_route: str | None = None,
    workspace_id: str | None = None,
) -> AnalysisAgentResponse:
    profile = build_dataset_profile(upload_id, sheet_name, workspace_id=workspace_id)
    routes = suggest_routes(profile)
    prompt_text = prompt.strip().lower()
    selected_cards: list[AgentDecisionCard] = []
    plan: list[AnalysisAgentPlanStep] = [
        AnalysisAgentPlanStep(
            stepId="step_profile",
            title="读取数据画像",
            description="先基于当前上传数据的 profile 判断字段角色、质量问题和推荐路线。",
            status="completed",
        ),
        AnalysisAgentPlanStep(
            stepId="step_reason",
            title="生成解释卡",
            description="把建议动作改写成可解释、可确认的 decision cards。",
            status="completed",
        ),
        AnalysisAgentPlanStep(
            stepId="step_confirm",
            title="等待确认执行",
            description="涉及变换或运行 workflow 的动作，都会先解释收益与风险，再等待你确认。",
            status="planned",
        ),
    ]

    def append_transform_cards(keyword: str, transform_type: str) -> None:
        for recommendation in profile.recommendations:
            if recommendation.actionType != transform_type:
                continue
            what_detected, why_recommended, if_skipped, expected_change = _decision_card_story(
                action_type="transform",
                action_id=transform_type,
                columns=recommendation.columns,
                expected_benefit=recommendation.expectedBenefit,
                explanation=recommendation.description,
            )
            selected_cards.append(
                AgentDecisionCard(
                    cardId=f"card_{keyword}_{recommendation.recommendationId}",
                    title=recommendation.title,
                    explanation=recommendation.description,
                    actionType="transform",
                    actionId=transform_type,
                    columns=recommendation.columns,
                    expectedBenefit=recommendation.expectedBenefit,
                    requiresConfirmation=True,
                    whatDetected=what_detected,
                    whyRecommended=why_recommended,
                    ifSkipped=if_skipped,
                    expectedChange=expected_change,
                )
            )

    if any(token in prompt_text for token in ["常量", "constant"]):
        append_transform_cards("constant", "drop_constant_columns")
    if any(token in prompt_text for token in ["id", "identifier", "标识", "编号"]):
        append_transform_cards("identifier", "drop_identifier_columns")
    if any(token in prompt_text for token in ["缺失", "missing", "空值"]):
        selected_cards.extend(
            AgentDecisionCard(
                cardId=f"card_missing_{issue.columns[0] if issue.columns else 'dataset'}",
                title=issue.title,
                explanation=issue.description,
                actionType="observation",
                actionId="review_missing_strategy",
                columns=issue.columns,
                expectedBenefit="先确认缺失处理口径，再决定删除还是填补，可以避免后续 workflow 误读数据质量。",
                requiresConfirmation=False,
                whatDetected=issue.description,
                whyRecommended="先把缺失列单独拎出来确认，能避免把删除、填补和业务口径混在一起做。",
                ifSkipped="如果不先确认缺失策略，后续 workflow 的结果会掺杂数据处理假设，难以解释前后差异。",
                expectedChange="这一步本身不直接改数据，但会让后面的处理决策更透明。",
            )
            for issue in profile.issues
            if issue.issueType == "high_missing_rate"
        )
    if any(token in prompt_text for token in ["标准化", "归一化", "normalize", "cluster", "聚类"]):
        append_transform_cards("normalize", "normalize_numeric_features")

    route_keyword_map = {
        "forecast": ["预测", "forecast", "时间序列", "趋势"],
        "attribution": ["归因", "原因", "驱动", "下降", "上升"],
        "supervised_ml": ["监督", "machine learning", "ml", "模型", "回归", "分类"],
        "clustering": ["聚类", "cluster", "分群", "细分"],
    }
    for route in [*routes.recommendedRoutes, *routes.blockedRoutes]:
        keywords = route_keyword_map.get(route.analysisType, [])
        if selected_route == route.analysisType or any(token in prompt_text for token in keywords):
            what_detected, why_recommended, if_skipped, expected_change = _decision_card_story(
                action_type="workflow",
                action_id=route.analysisType,
                columns=[],
                expected_benefit="进入可配置 workflow 后，可以继续手动挑选目标列、特征列和运行参数，并查看可回放运行过程。",
                route=route,
                explanation="；".join(route.reasons[:2]) if route.reasons else f"当前数据可进入 {route.label} workflow。",
            )
            selected_cards.append(
                AgentDecisionCard(
                    cardId=f"card_route_{route.analysisType}",
                    title=f"进入{route.label}",
                    explanation="；".join(route.reasons[:2]) if route.reasons else f"当前数据可进入 {route.label} workflow。",
                    actionType="workflow",
                    actionId=route.analysisType,
                    columns=[],
                    expectedBenefit="进入可配置 workflow 后，可以继续手动挑选目标列、特征列和运行参数，并查看可回放运行过程。",
                    requiresConfirmation=False,
                    whatDetected=what_detected,
                    whyRecommended=why_recommended,
                    ifSkipped=if_skipped,
                    expectedChange=expected_change,
                )
            )

    if not selected_cards:
        top_recommendations = profile.recommendations[:2]
        selected_cards.extend(
            AgentDecisionCard(
                cardId=f"card_default_{recommendation.recommendationId}",
                title=recommendation.title,
                explanation=recommendation.description,
                actionType="transform" if recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"} else "routing",
                actionId=recommendation.actionType,
                columns=recommendation.columns,
                expectedBenefit=recommendation.expectedBenefit,
                requiresConfirmation=recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"},
                whatDetected=_decision_card_story(
                    action_type="transform" if recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"} else "observation",
                    action_id=recommendation.actionType,
                    columns=recommendation.columns,
                    expected_benefit=recommendation.expectedBenefit,
                    explanation=recommendation.description,
                )[0],
                whyRecommended=_decision_card_story(
                    action_type="transform" if recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"} else "observation",
                    action_id=recommendation.actionType,
                    columns=recommendation.columns,
                    expected_benefit=recommendation.expectedBenefit,
                    explanation=recommendation.description,
                )[1],
                ifSkipped=_decision_card_story(
                    action_type="transform" if recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"} else "observation",
                    action_id=recommendation.actionType,
                    columns=recommendation.columns,
                    expected_benefit=recommendation.expectedBenefit,
                    explanation=recommendation.description,
                )[2],
                expectedChange=_decision_card_story(
                    action_type="transform" if recommendation.actionType in {"drop_constant_columns", "drop_identifier_columns", "drop_high_missing_columns", "normalize_numeric_features"} else "observation",
                    action_id=recommendation.actionType,
                    columns=recommendation.columns,
                    expected_benefit=recommendation.expectedBenefit,
                    explanation=recommendation.description,
                )[3],
            )
            for recommendation in top_recommendations
        )
        if routes.recommendedRoutes:
            best_route = routes.recommendedRoutes[0]
            what_detected, why_recommended, if_skipped, expected_change = _decision_card_story(
                action_type="workflow",
                action_id=best_route.analysisType,
                columns=[],
                expected_benefit="如果你已经清楚目标，可以直接进入这条正式 workflow；如果还不清楚，可以先处理上面的数据质量建议。",
                route=best_route,
                explanation="；".join(best_route.reasons[:2]),
            )
            selected_cards.append(
                AgentDecisionCard(
                    cardId=f"card_best_route_{best_route.analysisType}",
                    title=f"当前最匹配：{best_route.label}",
                    explanation="；".join(best_route.reasons[:2]),
                    actionType="workflow",
                    actionId=best_route.analysisType,
                    expectedBenefit="如果你已经清楚目标，可以直接进入这条正式 workflow；如果还不清楚，可以先处理上面的数据质量建议。",
                    requiresConfirmation=False,
                    whatDetected=what_detected,
                    whyRecommended=why_recommended,
                    ifSkipped=if_skipped,
                    expectedChange=expected_change,
                )
            )

    warnings = []
    if any(issue.issueType == "suspected_identifier" for issue in profile.issues):
        warnings.append("当前数据含疑似标识列，直接进建模或聚类前建议先确认是否保留。")
    if any(issue.issueType == "duplicate_time_index" for issue in profile.issues):
        warnings.append("时间索引存在重复时，Forecast workflow 前最好先聚合或补充分组字段。")

    return AnalysisAgentResponse(
        summary=f"我先基于这份数据生成了 {len(selected_cards)} 张可执行解释卡。",
        message="我会先解释为什么建议这么做、预计带来什么收益；涉及数据变换和 workflow 启动的动作，都等你确认后再执行。",
        context=AgentDatasetContext(
            uploadId=upload_id,
            sheetName=sheet_name,
            currentPage=current_page,
            selectedRoute=selected_route,
            datasetProfile=profile,
            routeSuggestion=routes,
        ),
        plan=plan,
        decisionCards=selected_cards[:5],
        warnings=warnings,
    )


def _stage_blueprints_for_analysis(analysis_type: str) -> list[WorkflowStageDetail]:
    stage_map: dict[str, list[tuple[str, str, str]]] = {
        "attribution": [
            ("profile_dataset", "理解目标与切片", "确认业务指标、可解释字段和分组维度。"),
            ("rank_drivers", "生成驱动证据", "计算数值相关性与关键 driver 候选。"),
            ("slice_differences", "比较分组差异", "聚合关键分组，形成首轮归因快照。"),
            ("persist_artifacts", "写入快照", "把归因摘要和 artifact 落到实验容器。"),
        ],
        "supervised_ml": [
            ("profile_dataset", "校验目标与特征", "确认目标列、特征列与样本量是否适合监督学习。"),
            ("prepare_matrix", "编码与预处理", "对特征做编码、数值化和缺失补齐。"),
            ("train_baseline", "训练回归基线", "运行第一版线性回归 baseline。"),
            ("evaluate_model", "评估指标", "计算 MAE / RMSE / R² 并生成系数摘要。"),
            ("persist_artifacts", "写入实验快照", "持久化 workflow 状态、指标和结果 artifact。"),
        ],
        "clustering": [
            ("profile_dataset", "确认聚类特征", "检查可聚类数值列与样本量。"),
            ("normalize_features", "标准化特征", "把数值特征对齐到统一尺度。"),
            ("fit_clusters", "拟合聚类模型", "运行 NumPy KMeans baseline。"),
            ("summarize_clusters", "整理簇概览", "汇总簇大小、簇中心和气泡图数据。"),
            ("persist_artifacts", "写入实验快照", "持久化 cluster 结果与 artifact。"),
        ],
    }
    rows = stage_map.get(analysis_type, [("profile_dataset", "准备数据", "初始化 workflow。")])
    return [
        WorkflowStageDetail(stageId=stage_id, title=title, description=description, status="planned", progressPercent=0)
        for stage_id, title, description in rows
    ]


def _build_attribution_experiment_payload(
    *,
    experiment_id: str,
    profile: DatasetProfile,
    target_column: str | None,
    grouping_columns: list[str],
    upload_id: str,
    sheet_name: str,
) -> dict[str, Any]:
    df = read_sheet_dataframe(upload_id, sheet_name)
    resolved_target = target_column or (profile.targetCandidates[0] if profile.targetCandidates else None)
    if not resolved_target or resolved_target not in df.columns:
        raise AppError("归因分析需要先选择一个数值目标列。", code="ATTRIBUTION_TARGET_REQUIRED")
    numeric_candidates = [column for column in profile.numericColumns if column != resolved_target][:6]
    correlations: list[dict[str, Any]] = []
    for column in numeric_candidates:
        pair = df[[resolved_target, column]].dropna()
        if len(pair) < 3:
            continue
        corr = pair[resolved_target].corr(pair[column])
        if pd.notna(corr):
            correlations.append({"feature": column, "correlation": float(corr)})
    correlations.sort(key=lambda item: abs(item["correlation"]), reverse=True)
    group_column = grouping_columns[0] if grouping_columns else (profile.groupingCandidates[0] if profile.groupingCandidates else None)
    grouping_summary: list[dict[str, Any]] = []
    if group_column and group_column in df.columns:
        grouped = (
            df[[group_column, resolved_target]]
            .dropna()
            .groupby(group_column)[resolved_target]
            .agg(["mean", "count"])
            .sort_values("mean", ascending=False)
            .head(8)
        )
        grouping_summary = [
            {"group": str(index), "mean": float(row["mean"]), "count": int(row["count"])}
            for index, row in grouped.iterrows()
        ]

    artifact = AgentArtifact(
        artifactId=f"artifact_{uuid.uuid4().hex[:10]}",
        kind="summary",
        title="归因快照",
        summary=f"围绕 {resolved_target} 提取了相关性和分组差异证据。",
        sourceSkillId="start_attribution_workflow",
        createdAt=_utc_now(),
        reportCompatible=True,
        downloadable=False,
        markdown="\n".join(
            [
                f"目标列：{resolved_target}",
                "",
                "Top driver candidates:",
                *[f"- {item['feature']}: corr={item['correlation']:.3f}" for item in correlations[:5]],
                "",
                "Top grouped slices:",
                *[f"- {item['group']}: mean={item['mean']:.2f}, count={item['count']}" for item in grouping_summary[:5]],
            ]
        ),
        data={"targetColumn": resolved_target, "correlations": correlations, "groupingSummary": grouping_summary},
    )
    attribution = AttributionSnapshot(
        experimentId=experiment_id,
        updatedAt=_utc_now(),
        overview=AttributionSnapshotSection(
            title="Overview",
            summary=[
                f"当前围绕 {resolved_target} 生成了归因快照。",
                f"最强线性相关候选包括：{'、'.join(item['feature'] for item in correlations[:3]) if correlations else '暂无'}。",
            ],
            highlights=correlations[:5],
            askAgentPrompts=["这份数据最可能的主要驱动因素是什么？"],
        ),
        quickDiagnosis=AttributionSnapshotSection(
            title="Quick Diagnosis",
            summary=["优先建议先看 driver ranking 和分组差异。"],
            highlights=grouping_summary[:5],
            askAgentPrompts=["只看这个目标列，先给我一个管理层能理解的结论。"],
        ),
        anomalyResidualLab=AttributionSnapshotSection(title="Anomaly & Residual Lab", summary=["这一版先提供结构化归因快照，异常分析可继续交给 Agent。"]),
        deepAttribution=AttributionSnapshotSection(title="Deep Attribution", summary=["可以继续对数值驱动和分组差异做深挖。"], highlights=correlations[:6]),
        scenarioExecutiveOutput=AttributionSnapshotSection(title="Scenario & Executive Output", summary=["可继续生成图表、摘要和报告段落。"]),
        warnings=[],
    )
    return {
        "experimentName": f"{resolved_target} Attribution Analysis",
        "targetColumn": resolved_target,
        "recommendedModelId": "attribution_evidence",
        "bestMae": None,
        "modelCount": 1,
        "config": {"analysisType": "attribution", "targetColumn": resolved_target, "groupingColumns": grouping_columns},
        "metrics": [{"modelId": "attribution_evidence", "modelName": "Attribution Evidence", "rank": 1, "status": "success", "metrics": {"score": len(correlations)}}],
        "diagnostics": {"correlations": correlations, "groupingSummary": grouping_summary},
        "workflowState": {"stage": "completed", "selectedTarget": resolved_target, "selectedGroupingColumns": grouping_columns},
        "artifacts": [artifact],
        "attribution": attribution.model_dump(mode="json"),
        "summary": f"归因 workflow 已完成首轮分析：围绕 {resolved_target} 生成了驱动候选和分组差异快照。",
        "warnings": [],
    }


def _build_supervised_experiment_payload(
    *,
    experiment_id: str,
    profile: DatasetProfile,
    target_column: str | None,
    feature_columns: list[str],
    upload_id: str,
    sheet_name: str,
) -> dict[str, Any]:
    df = read_sheet_dataframe(upload_id, sheet_name)
    resolved_target = target_column or (profile.targetCandidates[0] if profile.targetCandidates else None)
    if not resolved_target or resolved_target not in df.columns:
        raise AppError("监督学习 workflow 需要选择一个数值目标列。", code="SUPERVISED_TARGET_REQUIRED")
    if resolved_target not in profile.numericColumns:
        raise AppError("第一版监督学习先支持数值目标列的回归基线。", code="SUPERVISED_TARGET_NUMERIC_REQUIRED")
    resolved_features = feature_columns or [
        column.name
        for column in profile.columns
        if column.name != resolved_target and not column.isConstant and not column.isPotentialIdentifier and column.inferredType in {"number", "boolean", "string"}
    ]
    if len(resolved_features) < 2:
        raise AppError("监督学习至少需要 2 个可用特征列。", code="SUPERVISED_FEATURES_REQUIRED")

    model_df = df[[resolved_target, *resolved_features]].copy()
    model_df = model_df.dropna(subset=[resolved_target])
    encoded = pd.get_dummies(model_df[resolved_features], dummy_na=False)
    encoded = encoded.apply(pd.to_numeric, errors="coerce").fillna(encoded.mean()).fillna(0)
    target = pd.to_numeric(model_df[resolved_target], errors="coerce")
    valid_mask = target.notna()
    encoded = encoded.loc[valid_mask]
    target = target.loc[valid_mask]
    if len(encoded) < 10:
        raise AppError("有效训练样本过少，暂时无法运行监督学习基线。", code="SUPERVISED_SAMPLE_TOO_SMALL")

    split_index = max(1, int(len(encoded) * 0.8))
    train_x = encoded.iloc[:split_index].to_numpy(dtype=float)
    test_x = encoded.iloc[split_index:].to_numpy(dtype=float)
    train_y = target.iloc[:split_index].to_numpy(dtype=float)
    test_y = target.iloc[split_index:].to_numpy(dtype=float)
    if len(test_x) == 0:
        raise AppError("测试集为空，请提供更多样本后重试。", code="SUPERVISED_TEST_EMPTY")

    train_design = np.hstack([np.ones((len(train_x), 1)), train_x])
    coefficients, *_ = np.linalg.lstsq(train_design, train_y, rcond=None)
    test_design = np.hstack([np.ones((len(test_x), 1)), test_x])
    predictions = test_design @ coefficients
    mae = float(np.mean(np.abs(predictions - test_y)))
    rmse = float(np.sqrt(np.mean((predictions - test_y) ** 2)))
    denom = float(np.sum((test_y - np.mean(test_y)) ** 2))
    r2 = float(1 - np.sum((test_y - predictions) ** 2) / denom) if denom > 0 else 0.0

    feature_names = ["intercept", *encoded.columns.tolist()]
    coeff_rows = [
        {"feature": name, "coefficient": float(value)}
        for name, value in zip(feature_names, coefficients.tolist(), strict=False)
    ]
    coeff_rows = sorted(coeff_rows[1:], key=lambda item: abs(item["coefficient"]), reverse=True)[:10]

    artifact = AgentArtifact(
        artifactId=f"artifact_{uuid.uuid4().hex[:10]}",
        kind="summary",
        title="监督学习基线结果",
        summary=f"线性回归 baseline 完成，MAE {mae:.3f}，RMSE {rmse:.3f}，R² {r2:.3f}。",
        sourceSkillId="start_supervised_ml_workflow",
        createdAt=_utc_now(),
        reportCompatible=True,
        downloadable=False,
        markdown="\n".join(
            [
                f"Target: {resolved_target}",
                f"MAE: {mae:.4f}",
                f"RMSE: {rmse:.4f}",
                f"R²: {r2:.4f}",
                "",
                "Top coefficients:",
                *[f"- {item['feature']}: {item['coefficient']:.4f}" for item in coeff_rows[:8]],
            ]
        ),
        data={"metrics": {"mae": mae, "rmse": rmse, "r2": r2}, "coefficients": coeff_rows},
    )
    return {
        "experimentName": f"{resolved_target} Supervised ML Baseline",
        "targetColumn": resolved_target,
        "recommendedModelId": "linear_regression",
        "bestMae": mae,
        "modelCount": 1,
        "config": {"analysisType": "supervised_ml", "targetColumn": resolved_target, "featureColumns": resolved_features},
        "metrics": [{"modelId": "linear_regression", "modelName": "Linear Regression", "rank": 1, "status": "success", "metrics": {"mae": mae, "rmse": rmse, "r2": r2}}],
        "backtest": {
            "predictions": {
                "linear_regression": [
                    {"time": str(index), "actual": float(actual), "predicted": float(predicted), "residual": float(actual - predicted)}
                    for index, (actual, predicted) in enumerate(zip(test_y.tolist(), predictions.tolist(), strict=False), start=1)
                ]
            }
        },
        "diagnostics": {"sampleCount": int(len(encoded)), "featureCount": int(encoded.shape[1]), "coefficients": coeff_rows},
        "workflowState": {"stage": "completed", "selectedTarget": resolved_target, "selectedFeatures": resolved_features},
        "artifacts": [artifact],
        "summary": f"监督学习 workflow 已完成一轮 tabular 回归基线，当前 MAE 为 {mae:.3f}。",
        "warnings": ["第一版先使用线性回归 baseline，后续可以继续扩展树模型与分类器。"],
    }


def _build_clustering_experiment_payload(
    *,
    experiment_id: str,
    profile: DatasetProfile,
    feature_columns: list[str],
    cluster_count: int | None,
    upload_id: str,
    sheet_name: str,
) -> dict[str, Any]:
    df = read_sheet_dataframe(upload_id, sheet_name)
    resolved_features = feature_columns or [
        column.name
        for column in profile.columns
        if column.inferredType == "number" and not column.isConstant and not column.isPotentialIdentifier
    ]
    if len(resolved_features) < 2:
        raise AppError("聚类分析至少需要 2 个数值特征列。", code="CLUSTERING_FEATURES_REQUIRED")
    matrix = df[resolved_features].apply(pd.to_numeric, errors="coerce")
    matrix = matrix.fillna(matrix.mean()).fillna(0)
    if len(matrix) < 8:
        raise AppError("样本量过少，暂时不建议做聚类分析。", code="CLUSTERING_SAMPLE_TOO_SMALL")
    normalized = (matrix - matrix.mean()) / matrix.std(ddof=0).replace(0, 1)
    values = normalized.to_numpy(dtype=float)
    k = cluster_count or min(3, max(2, len(values) // 20 or 2))
    k = max(2, min(k, len(values)))
    labels, centroids, inertia = _kmeans_numpy(values, k)

    cluster_sizes = [
        {"cluster": int(index), "size": int((labels == index).sum())}
        for index in range(k)
    ]
    centroid_rows = [
        {"cluster": int(index), **{feature: float(value) for feature, value in zip(resolved_features, centroids[index].tolist(), strict=False)}}
        for index in range(k)
    ]
    artifact = AgentArtifact(
        artifactId=f"artifact_{uuid.uuid4().hex[:10]}",
        kind="chart",
        title="聚类概览",
        summary=f"KMeans baseline 完成，形成 {k} 个簇，inertia={inertia:.3f}。",
        sourceSkillId="start_clustering_workflow",
        createdAt=_utc_now(),
        reportCompatible=True,
        downloadable=False,
        data={
            "chartType": "bubble",
            "points": [
                {
                    "label": f"Cluster {row['cluster']}",
                    "x": row[resolved_features[0]],
                    "y": row[resolved_features[1]],
                    "size": next((item["size"] for item in cluster_sizes if item["cluster"] == row["cluster"]), 0),
                }
                for row in centroid_rows
            ],
            "summary": [f"Cluster {item['cluster']}: {item['size']} rows" for item in cluster_sizes],
        },
        markdown="\n".join(
            [
                f"Cluster count: {k}",
                f"Inertia: {inertia:.4f}",
                "",
                "Cluster sizes:",
                *[f"- Cluster {item['cluster']}: {item['size']}" for item in cluster_sizes],
            ]
        ),
    )
    return {
        "experimentName": "Clustering Baseline",
        "targetColumn": "cluster_label",
        "recommendedModelId": "kmeans_numpy",
        "bestMae": None,
        "modelCount": 1,
        "config": {"analysisType": "clustering", "featureColumns": resolved_features, "clusterCount": k},
        "metrics": [{"modelId": "kmeans_numpy", "modelName": "KMeans (NumPy)", "rank": 1, "status": "success", "metrics": {"inertia": float(inertia)}}],
        "diagnostics": {"featureCount": len(resolved_features), "clusterCount": k, "clusterSizes": cluster_sizes, "centroids": centroid_rows},
        "workflowState": {"stage": "completed", "selectedFeatures": resolved_features, "clusterCount": k},
        "artifacts": [artifact],
        "summary": f"聚类 workflow 已完成，当前形成 {k} 个簇，可继续下钻每个 cluster 的特征差异。",
        "warnings": ["第一版使用 NumPy KMeans baseline，后续可以继续扩展 silhouette 等诊断。"],
    }


def _kmeans_numpy(values: np.ndarray, cluster_count: int, max_iter: int = 30) -> tuple[np.ndarray, np.ndarray, float]:
    if cluster_count <= 0 or len(values) < cluster_count:
        raise AppError("聚类簇数超过样本量。", code="CLUSTERING_INVALID_K")
    centroids = values[:cluster_count].copy()
    labels = np.zeros(len(values), dtype=int)
    for _ in range(max_iter):
        distances = np.linalg.norm(values[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels
        for index in range(cluster_count):
            members = values[labels == index]
            if len(members):
                centroids[index] = members.mean(axis=0)
    inertia = float(np.sum((values - centroids[labels]) ** 2))
    return labels, centroids, inertia
