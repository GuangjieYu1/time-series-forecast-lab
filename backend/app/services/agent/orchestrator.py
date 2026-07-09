from __future__ import annotations

import json
import math
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.models import AgentRunRecord, ExperimentRecord, ReportRecord
from app.db.session import SessionLocal
from app.schemas import (
    AgentArtifact,
    AgentContextSnapshot,
    AgentMessage,
    AgentPlanStep,
    AgentRunEvent,
    AgentRunRequest,
    AgentSkillInvocation,
    AgentSkillDefinition,
)
from app.services.agent.policy import plan_risks
from app.services.agent.run_store import (
    append_artifact,
    append_event,
    append_message,
    get_agent_run,
    is_cancel_requested,
    replace_plan,
    to_agent_run_detail,
    update_run_status,
    upsert_invocation,
    utc_iso,
)
from app.services.agent.skill_registry import get_skill_definition, list_available_agent_skills
from app.services.attribution_snapshot import load_attribution_snapshot
from app.services.deepseek import build_report_context
from app.services.explainability import load_experiment_explainability
from app.services.runtime_history import load_runtime_from_record


@dataclass
class SkillExecutionResult:
    output_summary: str
    warnings: list[str] = field(default_factory=list)
    artifacts: list[AgentArtifact] = field(default_factory=list)
    scratch: dict[str, Any] = field(default_factory=dict)


def list_agent_skills() -> list[AgentSkillDefinition]:
    return list_available_agent_skills()


def plan_agent_run(*, request: AgentRunRequest, context: AgentContextSnapshot) -> tuple[list[AgentPlanStep], str, list[str]]:
    skill_ids = _select_skill_ids(request.prompt)
    steps: list[AgentPlanStep] = []
    for index, skill_id in enumerate(skill_ids, start=1):
        definition = get_skill_definition(skill_id)
        steps.append(
            AgentPlanStep(
                stepId=f"step_{index}",
                title=definition.label,
                skillId=skill_id,
                status="pending",
                description=definition.description,
                reads=definition.requiredInputs if definition.category == "read" else [],
                runs=[definition.label] if definition.category != "read" else [],
                generates=["artifact"] if definition.producesArtifacts else [],
                sideEffects=definition.sideEffects,
            )
        )
    will_run_models = any(skill_id.startswith("rerun_") for skill_id in skill_ids)
    risks = plan_risks(request, context, will_run_models=will_run_models)
    estimated_duration = _estimate_duration(skill_ids)
    return steps, estimated_duration, risks


class AttributionAgentOrchestrator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def start(self, run_id: str) -> None:
        with self._lock:
            current = self._threads.get(run_id)
            if current is not None and current.is_alive():
                return
            thread = threading.Thread(target=self._execute_run, args=(run_id,), daemon=True, name=f"agent-run-{run_id}")
            self._threads[run_id] = thread
            thread.start()

    def _execute_run(self, run_id: str) -> None:
        db = SessionLocal()
        try:
            record = get_agent_run(db, run_id)
            if record is None:
                return
            detail = to_agent_run_detail(record)
            if not detail.request.autoExecute:
                return
            update_run_status(db, run_id, "running")
            append_event(
                db,
                run_id,
                AgentRunEvent(
                    eventId=f"evt_{uuid.uuid4().hex[:10]}",
                    type="status",
                    title="Execution started",
                    detail="Agent 已开始执行本轮计划。",
                    timestamp=utc_iso(),
                    status="running",
                ),
            )
            bundle = _load_bundle(record.experiment_id)
            plan = detail.plan
            scratch: dict[str, Any] = {"runCreatedByUserId": record.created_by_user_id}
            for index, step in enumerate(plan):
                if is_cancel_requested(db, run_id):
                    step.status = "cancelled"
                    step.finishedAt = utc_iso()
                    replace_plan(db, run_id, plan)
                    append_event(
                        db,
                        run_id,
                        AgentRunEvent(
                            eventId=f"evt_{uuid.uuid4().hex[:10]}",
                            type="status",
                            title="Cancelled",
                            detail="Agent 收到停止指令，当前运行已中断。",
                            timestamp=utc_iso(),
                            stepId=step.stepId,
                            skillId=step.skillId,
                            status="cancelled",
                        ),
                    )
                    append_message(db, run_id, AgentMessage(role="assistant", content="本轮 Agent 已按你的要求停止，已保留已生成的中间 artifacts。", createdAt=utc_iso()))
                    update_run_status(db, run_id, "cancelled", "本轮运行已被用户中断。")
                    return

                invocation = AgentSkillInvocation(
                    invocationId=f"ainvoke_{uuid.uuid4().hex[:10]}",
                    skillId=step.skillId,
                    status="running",
                    inputSummary=", ".join(step.reads + step.runs) if (step.reads or step.runs) else "context-only",
                    startedAt=utc_iso(),
                )
                step.status = "running"
                step.startedAt = invocation.startedAt
                replace_plan(db, run_id, plan)
                upsert_invocation(db, run_id, invocation)
                append_event(
                    db,
                    run_id,
                    AgentRunEvent(
                        eventId=f"evt_{uuid.uuid4().hex[:10]}",
                        type="skill",
                        title=f"Running {step.title}",
                        detail=step.description,
                        timestamp=utc_iso(),
                        stepId=step.stepId,
                        skillId=step.skillId,
                        status="running",
                    ),
                )
                time.sleep(0.08)
                try:
                    result = _execute_skill(step.skillId, bundle=bundle, scratch=scratch, request=detail.request, context=detail.context)
                    scratch.update(result.scratch)
                    step.status = "completed"
                    step.outputSummary = result.output_summary
                    step.warnings = result.warnings
                    step.finishedAt = utc_iso()
                    invocation.status = "completed"
                    invocation.outputSummary = result.output_summary
                    invocation.warnings = result.warnings
                    invocation.finishedAt = step.finishedAt
                    for artifact in result.artifacts:
                        append_artifact(db, run_id, artifact)
                        invocation.artifactIds.append(artifact.artifactId)
                        append_event(
                            db,
                            run_id,
                            AgentRunEvent(
                                eventId=f"evt_{uuid.uuid4().hex[:10]}",
                                type="artifact",
                                title=artifact.title,
                                detail=artifact.summary,
                                timestamp=artifact.createdAt,
                                stepId=step.stepId,
                                skillId=step.skillId,
                                artifactId=artifact.artifactId,
                                status="completed",
                            ),
                        )
                    replace_plan(db, run_id, plan)
                    upsert_invocation(db, run_id, invocation)
                except Exception as exc:
                    step.status = "failed"
                    step.error = str(exc)
                    step.finishedAt = utc_iso()
                    invocation.status = "failed"
                    invocation.error = str(exc)
                    invocation.finishedAt = step.finishedAt
                    replace_plan(db, run_id, plan)
                    upsert_invocation(db, run_id, invocation)
                    append_event(
                        db,
                        run_id,
                        AgentRunEvent(
                            eventId=f"evt_{uuid.uuid4().hex[:10]}",
                            type="error",
                            title=f"{step.title} failed",
                            detail=str(exc),
                            timestamp=utc_iso(),
                            stepId=step.stepId,
                            skillId=step.skillId,
                            status="failed",
                        ),
                    )
                    append_message(db, run_id, AgentMessage(role="assistant", content=f"步骤“{step.title}”失败：{exc}", createdAt=utc_iso()))
                    update_run_status(db, run_id, "failed", f"运行在 {step.title} 失败。")
                    return

            final_summary = _build_final_summary(scratch, bundle, request=detail.request)
            append_message(db, run_id, AgentMessage(role="assistant", content=final_summary, createdAt=utc_iso()))
            append_event(
                db,
                run_id,
                AgentRunEvent(
                    eventId=f"evt_{uuid.uuid4().hex[:10]}",
                    type="status",
                    title="Completed",
                    detail="Agent 已完成本轮计划，结果可回放。",
                    timestamp=utc_iso(),
                    status="completed",
                ),
            )
            update_run_status(db, run_id, "completed", final_summary)
        finally:
            db.close()
            with self._lock:
                self._threads.pop(run_id, None)


agent_orchestrator = AttributionAgentOrchestrator()


def _estimate_duration(skill_ids: list[str]) -> str:
    seconds = 0
    for skill_id in skill_ids:
        definition = get_skill_definition(skill_id)
        if definition.costLevel == "high":
            seconds += 20
        elif definition.costLevel == "medium":
            seconds += 8
        else:
            seconds += 3
    if seconds < 10:
        return "<10s"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def _select_skill_ids(prompt: str) -> list[str]:
    text = prompt.lower()
    skill_ids: list[str] = []

    def include(*items: str):
        for item in items:
            if item not in skill_ids:
                skill_ids.append(item)

    include("read_attribution_snapshot", "read_residual_diagnostics")
    if any(keyword in prompt for keyword in ["特征", "驱动", "原因", "下降", "上升", "解释"]):
        include("read_explainability", "driver_ranking")
    if "协变量" in prompt or "泄漏" in prompt:
        include("read_covariate_flow", "control_variable_view")
    if "runtime" in text or "耗时" in prompt or "阶段" in prompt:
        include("read_runtime")
    if "feature" in text or "工厂" in prompt:
        include("read_feature_factory")
    if "异常" in prompt:
        include("anomaly_detection_zscore")
    if "同比" in prompt or "环比" in prompt or "mom" in text or "yoy" in text:
        include("yoy_mom_anomaly_check")
    if "季节性" in prompt:
        include("seasonality_normalization")
    if "树" in prompt or "shap" in text or "importance" in text:
        include("tree_driver_analysis")
    if "回归" in prompt:
        include("regression_attribution")
    if "敏感性" in prompt:
        include("sensitivity_analysis")
    if "弹性" in prompt:
        include("elasticity_analysis")
    if "benchmark" in text or "基线" in prompt or "第二名" in prompt or "对比" in prompt:
        include("benchmark_gap_analysis")
    if "分层" in prompt or "层级" in prompt or "国际航线" in prompt:
        include("hierarchical_drilldown")
    if "瀑布" in prompt:
        include("generate_waterfall_chart", "image_insight_caption")
    if "热力图" in prompt:
        include("generate_heatmap", "image_insight_caption")
    if "气泡" in prompt or "散点" in prompt:
        include("generate_bubble_chart", "image_insight_caption")
    if "图片" in prompt or "图像" in prompt or "caption" in text:
        include("read_existing_visual", "image_insight_caption")
    if "报告" in prompt and ("完整" in prompt or "全文" in prompt or "full" in text):
        include("generate_full_report")
    elif "报告" in prompt or "写进报告" in prompt or "报告段落" in prompt:
        include("generate_report_section")
    if "scenario" in text or "情景" in prompt:
        include("run_scenario_analysis")
    if "monte carlo" in text or "蒙特卡洛" in prompt:
        include("run_monte_carlo")
    if "重跑" in prompt and "模型" in prompt:
        include("rerun_model_subset")
    elif "重跑" in prompt and "协变量" in prompt:
        include("rerun_covariate_strategy_experiment")
    elif "重跑" in prompt or "重新回测" in prompt:
        include("rerun_backtest_with_config")
    include("executive_summary_writeback")
    return skill_ids


def _load_bundle(experiment_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        record = db.get(ExperimentRecord, experiment_id)
        if record is None:
            raise ValueError("Experiment not found for agent run.")
        reports = db.scalars(select(ReportRecord).where(ReportRecord.experiment_id == experiment_id).order_by(ReportRecord.created_at.desc())).all()
        config = _loads(record.config_json, {})
        data_profile = _loads(record.data_profile_json, {})
        backtest = _loads(record.backtest_json, {})
        diagnostics = _loads(record.diagnostics_json, {})
        series = _loads(record.series_json, [])
        final_forecast = _loads(record.final_forecast_json, None)
        model_logs = _loads(record.model_logs_json, [])
        runtime = load_runtime_from_record(record)
        explainability = load_experiment_explainability(record.id, record.recommended_model_id, model_logs)
        attribution = load_attribution_snapshot(record)
        report_context = build_report_context(
            {
                "experimentId": record.id,
                "experimentName": record.name,
                "fileName": record.file_name,
                "sheetName": record.sheet_name,
                "targetColumn": record.target_column,
                "recommendedModelId": record.recommended_model_id,
                "bestMae": _safe_float(record.best_mae),
                "createdAt": record.created_at.isoformat(),
                "config": config,
                "dataProfile": data_profile,
                "rankedModels": _loads(record.metrics_json, []),
                "backtest": backtest,
                "diagnostics": diagnostics,
                "dataHealth": None,
                "finalForecast": final_forecast,
                "modelLogs": model_logs,
                "runtime": runtime.model_dump(mode="json") if runtime else None,
                "manifest": _loads(record.manifest_json, None),
            }
        )
        return {
            "record": record,
            "reports": reports,
            "config": config,
            "dataProfile": data_profile,
            "rankedModels": _loads(record.metrics_json, []),
            "backtest": backtest,
            "diagnostics": diagnostics,
            "series": series,
            "finalForecast": final_forecast,
            "modelLogs": model_logs,
            "runtime": runtime,
            "explainability": explainability,
            "attribution": attribution,
            "manifest": _loads(record.manifest_json, None),
            "reportContext": report_context,
        }
    finally:
        db.close()


def _execute_skill(
    skill_id: str,
    *,
    bundle: dict[str, Any],
    scratch: dict[str, Any],
    request: AgentRunRequest,
    context: AgentContextSnapshot,
) -> SkillExecutionResult:
    match skill_id:
        case "read_runtime":
            runtime = bundle.get("runtime")
            if runtime is None:
                return SkillExecutionResult("当前实验没有可回放的 runtime。", warnings=["runtime snapshot missing"])
            summary = f"Runtime 共记录 {len(runtime.models)} 个模型，当前推荐模型 {bundle['record'].recommended_model_id or '未知'}。"
            scratch["runtimeSummary"] = summary
            return SkillExecutionResult(summary, scratch={"runtimeSummary": summary})
        case "read_feature_factory":
            runtime = bundle.get("runtime")
            target = runtime.featurePipeline[0] if runtime and runtime.featurePipeline else None
            if target is None:
                return SkillExecutionResult("当前实验没有 Feature Factory 快照。", warnings=["feature pipeline missing"])
            summary = f"Feature Factory 里生成 {target.summary.generatedFeatureCount if target.summary else len(target.lineage)} 个特征，保留 {target.summary.selectedFeatureCount if target.summary else 0} 个。"
            scratch["featureFactorySummary"] = summary
            return SkillExecutionResult(summary, scratch={"featureFactorySummary": summary})
        case "read_explainability":
            explainability = bundle["explainability"]
            recommended = next((item for item in explainability.models if item.modelId == explainability.recommendedModelId), None) or (explainability.models[0] if explainability.models else None)
            if recommended is None:
                return SkillExecutionResult("当前实验没有 explainability 结果。")
            top_features = [item.feature for item in (recommended.shapTopFeatures or recommended.featureImportance)[:3]]
            summary = f"推荐模型 {_model_label(recommended.modelName, recommended.modelId)} 的主要特征包括：{'、'.join(top_features) if top_features else '暂无'}。"
            scratch["topExplainabilityFeatures"] = top_features
            return SkillExecutionResult(summary, scratch={"topExplainabilityFeatures": top_features})
        case "read_residual_diagnostics":
            rows = _prediction_rows(bundle)
            largest = max(rows, key=lambda row: abs(_safe_float(row.get('residual')) or 0.0), default=None)
            mean_abs = statistics.mean(abs(_safe_float(row.get("residual")) or 0.0) for row in rows) if rows else None
            summary = (
                f"最大 residual 出现在 {largest.get('time')}，残差 {(_safe_float(largest.get('residual')) or 0.0):.4f}；平均绝对 residual {mean_abs:.4f}。"
                if largest and mean_abs is not None
                else "当前没有足够的 residual 诊断点。"
            )
            scratch["largestResidual"] = largest
            return SkillExecutionResult(summary, scratch={"largestResidual": largest})
        case "read_covariate_flow":
            covariates = _covariates(bundle)
            if not covariates:
                return SkillExecutionResult("当前实验没有启用 covariates。")
            summary = "；".join(
                f"{item.name}: {item.type}, backtest={item.backtestStrategy}, forecast={item.forecastStrategy}"
                for item in covariates[:5]
            )
            return SkillExecutionResult(summary, warnings=[item.note for item in covariates if item.note][:3])
        case "read_manifest":
            manifest = bundle.get("manifest") or {}
            summary = f"Manifest config hash: {manifest.get('configHash') or bundle['record'].config_hash or 'unknown'}。"
            return SkillExecutionResult(summary)
        case "read_report":
            reports = bundle.get("reports") or []
            if not reports:
                return SkillExecutionResult("当前实验还没有已有报告。")
            latest = reports[0]
            excerpt = latest.content_markdown[:140].replace("\n", " ")
            return SkillExecutionResult(f"最新报告 {latest.id} 摘要：{excerpt}")
        case "read_existing_visual":
            available = ["backtest_curve", "residual_timeline", "metric_ranking"]
            if bundle.get("finalForecast"):
                available.append("final_forecast")
            summary = "当前可读取的图表包括：" + "、".join(available)
            scratch["availableVisuals"] = available
            return SkillExecutionResult(summary, scratch={"availableVisuals": available})
        case "read_attribution_snapshot":
            attribution = bundle["attribution"]
            summary = attribution.overview.summary[0] if attribution.overview.summary else "当前实验暂无 attribution snapshot 摘要。"
            return SkillExecutionResult(summary)
        case "anomaly_detection_zscore":
            artifact = _anomaly_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已完成 z-score 异常检测。", artifacts=[artifact], scratch={"latestAnomalyArtifact": artifact.data})
        case "yoy_mom_anomaly_check":
            artifact = _mom_yoy_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已完成同比/环比异常检查。", artifacts=[artifact], scratch={"latestChangeArtifact": artifact.data})
        case "seasonality_normalization":
            artifact = _seasonality_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已完成季节性归一检查。", artifacts=[artifact], scratch={"latestSeasonalityArtifact": artifact.data})
        case "driver_ranking":
            artifact = _driver_ranking_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成 driver ranking。", artifacts=[artifact], scratch={"driverRanking": artifact.data})
        case "hierarchical_drilldown":
            artifact = _hierarchical_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成分层下钻建议。", artifacts=[artifact])
        case "control_variable_view":
            artifact = _control_variable_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已整理协变量控制视图。", artifacts=[artifact])
        case "tree_driver_analysis":
            artifact = _tree_driver_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已读取树模型驱动解释。", artifacts=[artifact])
        case "regression_attribution":
            artifact = _regression_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成回归归因 best-effort 说明。", artifacts=[artifact], warnings=["当前版本默认不持久化完整训练特征矩阵，因此这部分是证据汇总而非重新拟合。"])
        case "sensitivity_analysis":
            artifact = _sensitivity_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成敏感性分析。", artifacts=[artifact])
        case "elasticity_analysis":
            artifact = _elasticity_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成弹性分析。", artifacts=[artifact])
        case "benchmark_gap_analysis":
            artifact = _benchmark_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已完成 benchmark gap 分析。", artifacts=[artifact])
        case "image_insight_caption":
            artifact = _image_caption_artifact(scratch=scratch, source_skill_id=skill_id)
            return SkillExecutionResult("已为最新图表补充图片解读。", artifacts=[artifact])
        case "executive_summary_writeback":
            artifact = _executive_summary_artifact(bundle, scratch=scratch, request=request, source_skill_id=skill_id)
            return SkillExecutionResult("已生成管理层摘要。", artifacts=[artifact], scratch={"executiveSummary": artifact.markdown or artifact.summary})
        case "generate_waterfall_chart":
            artifact = _waterfall_chart_artifact(bundle, scratch=scratch, source_skill_id=skill_id)
            return SkillExecutionResult("已生成瀑布图。", artifacts=[artifact], scratch={"latestChartArtifact": artifact.data})
        case "generate_heatmap":
            artifact = _heatmap_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成热力图。", artifacts=[artifact], scratch={"latestChartArtifact": artifact.data})
        case "generate_bubble_chart":
            artifact = _bubble_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成气泡图。", artifacts=[artifact], scratch={"latestChartArtifact": artifact.data})
        case "generate_report_section":
            artifact = _report_section_artifact(bundle, scratch=scratch, request=request, source_skill_id=skill_id)
            return SkillExecutionResult("已生成报告段落。", artifacts=[artifact], scratch={"latestReportSection": artifact.markdown})
        case "generate_full_report":
            artifact = _full_report_artifact(bundle, scratch=scratch, source_skill_id=skill_id)
            return SkillExecutionResult("已生成新的归因报告记录。", artifacts=[artifact])
        case "run_scenario_analysis":
            artifact = _scenario_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成情景分析。", artifacts=[artifact], scratch={"latestScenario": artifact.data})
        case "run_monte_carlo":
            artifact = _monte_carlo_artifact(bundle, source_skill_id=skill_id)
            return SkillExecutionResult("已生成 Monte Carlo 概率图。", artifacts=[artifact], scratch={"latestScenario": artifact.data})
        case "rerun_backtest_with_config" | "rerun_model_subset" | "rerun_covariate_strategy_experiment":
            artifact = _rerun_restriction_artifact(skill_id=skill_id, request=request)
            return SkillExecutionResult("已返回可执行限制说明。", artifacts=[artifact], warnings=["当前版本不会在缺少源上传上下文时假装重跑。"])
        case _:
            return SkillExecutionResult(f"Skill {skill_id} 当前尚未实现。", warnings=["unimplemented skill"])


def _prediction_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    backtest = bundle.get("backtest") or {}
    predictions = backtest.get("predictions") if isinstance(backtest, dict) else None
    if not isinstance(predictions, dict):
        return []
    model_id = bundle["record"].recommended_model_id
    rows = predictions.get(model_id)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _covariates(bundle: dict[str, Any]):
    runtime = bundle.get("runtime")
    return runtime.featurePipeline[0].covariates if runtime and runtime.featurePipeline else []


def _history_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in bundle.get("series") or [] if isinstance(row, dict)]


def _driver_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    explainability = bundle["explainability"]
    recommended = next((item for item in explainability.models if item.modelId == explainability.recommendedModelId), None) or (explainability.models[0] if explainability.models else None)
    if recommended is None:
        return []
    rows: list[dict[str, Any]] = []
    for item in recommended.shapTopFeatures[:8]:
        rows.append({"feature": item.feature, "score": item.meanAbsShap or 0.0, "direction": item.direction or "mixed", "evidence": "SHAP"})
    if rows:
        return rows
    for item in recommended.featureImportance[:8]:
        rows.append({"feature": item.feature, "score": item.importance or 0.0, "direction": item.direction or "mixed", "evidence": "Importance"})
    return rows


def _anomaly_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = _history_rows(bundle)
    values = [_safe_float(row.get("value")) or 0.0 for row in rows]
    mean = statistics.mean(values) if values else 0.0
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    items = []
    if stdev > 0:
        for row, value in zip(rows, values):
            z = (value - mean) / stdev
            if abs(z) >= 2:
                items.append({"time": row.get("time"), "value": value, "zscore": round(z, 4)})
    items = sorted(items, key=lambda item: abs(item["zscore"]), reverse=True)[:12]
    return _artifact(
        kind="table",
        title="Z-score 异常检测",
        summary=f"检测到 {len(items)} 个 |z|≥2 的异常候选。",
        source_skill_id=source_skill_id,
        data={"columns": ["time", "value", "zscore"], "rows": items},
        markdown="\n".join(
            ["## Z-score 异常检测", "", f"- 检测到 {len(items)} 个异常候选。"] + [f"- {item['time']}：value={item['value']:.2f}，z={item['zscore']:.2f}" for item in items[:6]]
        ),
        report_compatible=True,
    )


def _mom_yoy_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = _history_rows(bundle)
    deltas: list[dict[str, Any]] = []
    previous_value = None
    for row in rows:
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        if previous_value not in (None, 0):
            change = (value - previous_value) / abs(previous_value)
            deltas.append({"time": row.get("time"), "changeRate": round(change, 4), "value": value})
        previous_value = value
    top = sorted(deltas, key=lambda item: abs(item["changeRate"]), reverse=True)[:10]
    return _artifact(
        kind="table",
        title="同比 / 环比异常检查",
        summary=f"已提取 {len(top)} 个变化最剧烈的时间点。",
        source_skill_id=source_skill_id,
        data={"columns": ["time", "changeRate", "value"], "rows": top},
        markdown="\n".join(["## 同比 / 环比异常检查", ""] + [f"- {item['time']}：变化率 {item['changeRate']:.2%}" for item in top[:6]]),
        report_compatible=True,
    )


def _seasonality_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = _history_rows(bundle)
    buckets: dict[str, list[float]] = {}
    for row in rows:
        value = _safe_float(row.get("value"))
        timestamp = _parse_time(row.get("time"))
        if value is None or timestamp is None:
            continue
        key = f"{timestamp.month:02d}/{timestamp.weekday()}"
        buckets.setdefault(key, []).append(value)
    normalized = [{"bucket": key, "mean": round(statistics.mean(values), 4), "count": len(values)} for key, values in buckets.items()]
    normalized.sort(key=lambda item: item["mean"], reverse=True)
    return _artifact(
        kind="table",
        title="季节性归一检查",
        summary="已按 month / weekday 聚合历史值，用于判断异常是否仍然成立。",
        source_skill_id=source_skill_id,
        data={"columns": ["bucket", "mean", "count"], "rows": normalized[:12]},
        markdown="\n".join(["## 季节性归一检查", ""] + [f"- bucket {item['bucket']}：均值 {item['mean']}" for item in normalized[:6]]),
        report_compatible=True,
    )


def _driver_ranking_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    drivers = _driver_items(bundle)
    return _artifact(
        kind="table",
        title="Driver Ranking",
        summary=f"已汇总 {len(drivers)} 个驱动候选。",
        source_skill_id=source_skill_id,
        data={"columns": ["feature", "score", "direction", "evidence"], "rows": drivers},
        markdown="\n".join(["## Driver Ranking", ""] + [f"- {item['feature']}：{item['evidence']}={_format_metric(item['score'])}，方向 {item['direction']}" for item in drivers[:6]]),
        report_compatible=True,
    )


def _hierarchical_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    columns = bundle.get("dataProfile", {}).get("targets", [{}])[0].get("availableColumns") if isinstance(bundle.get("dataProfile", {}), dict) else []
    if not isinstance(columns, list):
        columns = []
    candidates = [str(column) for column in columns if any(token in str(column).lower() for token in ["route", "region", "market", "airport", "channel", "segment"])]
    summary = "可做层级下钻的候选字段：" + ("、".join(candidates) if candidates else "当前未持久化明确的层级维度，建议使用业务维表或额外上传。")
    return _artifact(kind="summary", title="Hierarchical Drilldown", summary=summary, source_skill_id=source_skill_id, data={"candidateColumns": candidates}, markdown=f"## 分层下钻建议\n\n{summary}", report_compatible=True)


def _control_variable_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = [
        {
            "name": item.name,
            "type": item.type,
            "backtestStrategy": item.backtestStrategy,
            "forecastStrategy": item.forecastStrategy,
            "leakageRisk": item.leakageRisk,
        }
        for item in _covariates(bundle)
    ]
    summary = f"共梳理 {len(rows)} 个协变量，其中 {sum(1 for item in rows if item['leakageRisk'])} 个需要重点关注泄漏风险。"
    return _artifact(kind="table", title="Control Variable View", summary=summary, source_skill_id=source_skill_id, data={"columns": ["name", "type", "backtestStrategy", "forecastStrategy", "leakageRisk"], "rows": rows}, markdown=f"## 协变量控制视图\n\n{summary}", report_compatible=True)


def _tree_driver_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    explainability = bundle["explainability"]
    recommended = next((item for item in explainability.models if item.modelId == explainability.recommendedModelId), None) or (explainability.models[0] if explainability.models else None)
    if recommended is None:
        return _artifact(kind="warning", title="Tree Driver Analysis", summary="当前实验没有 explainability 结果。", source_skill_id=source_skill_id, data={})
    summary = f"推荐模型 {_model_label(recommended.modelName, recommended.modelId)} 的前 5 个驱动为："
    body = [f"- {item.feature}：SHAP={_format_metric(item.meanAbsShap)}，方向={item.direction or '-'}" for item in recommended.shapTopFeatures[:5]]
    if not body:
        body = [f"- {item.feature}：importance={_format_metric(item.importance)}" for item in recommended.featureImportance[:5]]
    return _artifact(kind="markdown", title="Tree Driver Analysis", summary=summary, source_skill_id=source_skill_id, data={"modelId": recommended.modelId}, markdown="## Tree Driver Analysis\n\n" + summary + "\n" + "\n".join(body), report_compatible=True)


def _regression_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    summary = "当前版本没有持久化完整训练特征矩阵，因此回归归因采用已保存的 explainability / covariate flow / residual evidence 做 best-effort 解释。"
    return _artifact(kind="warning", title="Regression Attribution", summary=summary, source_skill_id=source_skill_id, data={"mode": "best_effort"}, markdown=f"## 回归归因\n\n{summary}", report_compatible=True)


def _sensitivity_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    drivers = _driver_items(bundle)[:5]
    rows = []
    total = sum(abs(float(item.get("score") or 0.0)) for item in drivers) or 1.0
    for item in drivers:
        weight = abs(float(item.get("score") or 0.0)) / total
        rows.append({"feature": item["feature"], "minus10": round(-10 * weight, 2), "plus10": round(10 * weight, 2)})
    return _artifact(kind="table", title="Sensitivity Analysis", summary="已按主要驱动权重生成 ±10% 变化的敏感性摘要。", source_skill_id=source_skill_id, data={"columns": ["feature", "minus10", "plus10"], "rows": rows}, markdown="\n".join(["## 敏感性分析", ""] + [f"- {row['feature']}：-10% -> {row['minus10']}，+10% -> {row['plus10']}" for row in rows]), report_compatible=True)


def _elasticity_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    drivers = _driver_items(bundle)
    price_like = [item for item in drivers if any(token in item["feature"].lower() for token in ["price", "promo", "discount", "fuel", "fare"])]
    summary = (
        "发现价格/促销类特征，可进一步把这些特征作为弹性分析优先对象。"
        if price_like
        else "当前主要驱动里没有明显的价格/促销类特征，因此这里只能给出方法建议。"
    )
    return _artifact(kind="summary", title="Elasticity Analysis", summary=summary, source_skill_id=source_skill_id, data={"candidateFeatures": price_like}, markdown=f"## 弹性分析\n\n{summary}", report_compatible=True)


def _benchmark_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    models = [row for row in bundle.get("rankedModels") or [] if isinstance(row, dict) and row.get("status") == "success"]
    rows = []
    for row in models[:6]:
        runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
        rows.append(
            {
                "model": _model_label(row.get("modelName"), row.get("modelId")),
                "mae": _metric(row, "mae"),
                "fitSeconds": _safe_float(runtime.get("fitSeconds")) or 0.0,
                "predictSeconds": _safe_float(runtime.get("predictSeconds")) or 0.0,
            }
        )
    return _artifact(kind="table", title="Benchmark Gap Analysis", summary="已整理推荐模型与其他模型的指标/耗时差距。", source_skill_id=source_skill_id, data={"columns": ["model", "mae", "fitSeconds", "predictSeconds"], "rows": rows}, markdown="\n".join(["## Benchmark Gap Analysis", ""] + [f"- {row['model']}：MAE={_format_metric(row['mae'])}，fit={row['fitSeconds']:.2f}s，predict={row['predictSeconds']:.2f}s" for row in rows[:6]]), report_compatible=True)


def _waterfall_chart_artifact(bundle: dict[str, Any], scratch: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = (scratch.get("driverRanking") or {}).get("rows") if isinstance(scratch.get("driverRanking"), dict) else None
    if not isinstance(rows, list) or not rows:
        rows = _driver_items(bundle)
    items = []
    for row in rows[:6]:
        score = abs(float(row.get("score") or 0.0))
        direction = str(row.get("direction") or "mixed")
        signed = score if direction == "positive" else -score if direction == "negative" else score * 0.5
        items.append({"label": row.get("feature"), "value": round(signed, 4), "direction": direction})
    return _artifact(kind="chart", title="归因瀑布图", summary="已基于主要驱动候选生成管理层版本瀑布图。注意：图中数值代表解释证据权重，不等同严格因果贡献。", source_skill_id=source_skill_id, data={"chartType": "waterfall", "items": items}, markdown="## 归因瀑布图\n\n- 已生成管理层版本瀑布图。\n- 图中数值代表解释证据权重，不等同严格因果贡献。", report_compatible=True)


def _heatmap_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = _prediction_rows(bundle)
    grid: dict[tuple[int, int], list[float]] = {}
    for row in rows:
        timestamp = _parse_time(row.get("time"))
        residual = _safe_float(row.get("residual"))
        if timestamp is None or residual is None:
            continue
        key = (timestamp.weekday(), timestamp.month)
        grid.setdefault(key, []).append(residual)
    x_labels = [str(month) for month in range(1, 13)]
    y_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    values = []
    for (weekday, month), items in grid.items():
        values.append([month - 1, weekday, round(statistics.mean(items), 4)])
    return _artifact(kind="chart", title="残差热力图", summary="已按 month × weekday 聚合 residual 均值。", source_skill_id=source_skill_id, data={"chartType": "heatmap", "xLabels": x_labels, "yLabels": y_labels, "values": values, "valueLabel": "Mean Residual"}, markdown="## 残差热力图\n\n- 已按 month × weekday 聚合 residual 均值。", report_compatible=True)


def _bubble_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    rows = []
    for item in bundle.get("rankedModels") or []:
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
        mae = _metric(item, "mae")
        if mae is None:
            continue
        fit = _safe_float(runtime.get("fitSeconds")) or 0.0
        predict = _safe_float(runtime.get("predictSeconds")) or 0.0
        rows.append({"label": _model_label(item.get("modelName"), item.get("modelId")), "x": fit + predict, "y": mae, "size": max(8, 36 - min(mae * 5, 24))})
    return _artifact(kind="chart", title="模型对比气泡图", summary="已生成模型耗时 × MAE 的气泡图。", source_skill_id=source_skill_id, data={"chartType": "bubble", "items": rows, "xLabel": "Fit + Predict Seconds", "yLabel": "MAE"}, markdown="## 模型对比气泡图\n\n- 已生成模型耗时 × MAE 的气泡图。", report_compatible=True)


def _report_section_artifact(bundle: dict[str, Any], scratch: dict[str, Any], request: AgentRunRequest, *, source_skill_id: str) -> AgentArtifact:
    summary = scratch.get("executiveSummary") or _build_final_summary(scratch, bundle, request=request)
    markdown = "\n".join(["## 归因结论补充", "", summary])
    return _artifact(kind="report", title="报告章节草稿", summary="已生成可直接复制到报告的章节草稿。", source_skill_id=source_skill_id, data={"sectionType": "attribution"}, markdown=markdown, report_compatible=True)


def _full_report_artifact(bundle: dict[str, Any], scratch: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    db = SessionLocal()
    try:
        record: ExperimentRecord = bundle["record"]
        reports: list[ReportRecord] = bundle.get("reports") or []
        summary = scratch.get("executiveSummary") or "本报告由 Attribution Agent 自动生成，基于当前实验的 residual、驱动排序和协变量策略。"
        markdown = "\n".join(
            [
                "# Attribution Agent Report",
                "",
                f"- 实验：{record.name}",
                f"- 目标列：{record.target_column}",
                f"- 推荐模型：{record.recommended_model_id or '未知'}",
                "",
                "## 管理层摘要",
                "",
                summary,
                "",
                "## 快速归因",
                "",
                *(f"- {line}" for line in bundle["attribution"].quickDiagnosis.summary[:3]),
                "",
                "## 驱动排序",
                "",
                *(
                    f"- {item['feature']}：{item['evidence']}={_format_metric(item['score'])}，方向 {item['direction']}"
                    for item in _driver_items(bundle)[:6]
                ),
                "",
                "## 协变量与风险",
                "",
                *(
                    f"- {item.name}: {item.type}, backtest={item.backtestStrategy}, forecast={item.forecastStrategy}, leakageRisk={item.leakageRisk}"
                    for item in _covariates(bundle)[:6]
                ),
            ]
        )
        report = ReportRecord(
            id=f"report_agent_{uuid.uuid4().hex[:10]}",
            experiment_id=record.id,
            workspace_id=record.workspace_id,
            created_by_user_id=str(scratch.get("runCreatedByUserId") or record.created_by_user_id),
            content_markdown=markdown,
            model="attribution-agent-v0.5.5",
        )
        db.add(report)
        db.commit()
        reports.insert(0, report)
        bundle["reports"] = reports
        return _artifact(kind="report", title="完整归因报告", summary=f"已创建新的报告记录 {report.id}。", source_skill_id=source_skill_id, data={"reportId": report.id}, markdown=markdown, report_compatible=True, downloadable=True)
    finally:
        db.close()


def _scenario_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    final_forecast = bundle.get("finalForecast") or {}
    forecast_rows = final_forecast.get("forecast") if isinstance(final_forecast, dict) else None
    rows = [row for row in forecast_rows if isinstance(row, dict)] if isinstance(forecast_rows, list) else []
    if not rows:
        rows = [{"time": row.get("time"), "predicted": row.get("actual")} for row in _prediction_rows(bundle)[-7:]]
    baseline = []
    up = []
    down = []
    for row in rows:
        predicted = _safe_float(row.get("predicted")) or 0.0
        baseline.append({"time": row.get("time"), "value": round(predicted, 4)})
        up.append({"time": row.get("time"), "value": round(predicted * 1.08, 4)})
        down.append({"time": row.get("time"), "value": round(predicted * 0.92, 4)})
    return _artifact(kind="chart", title="Scenario Analysis", summary="已生成 baseline / upside / downside 三种情景。", source_skill_id=source_skill_id, data={"chartType": "multi_line", "series": [{"name": "Baseline", "points": baseline}, {"name": "Upside", "points": up}, {"name": "Downside", "points": down}]}, markdown="## 情景分析\n\n- 已生成 baseline / upside / downside 三种情景。", report_compatible=True)


def _monte_carlo_artifact(bundle: dict[str, Any], *, source_skill_id: str) -> AgentArtifact:
    residuals = [abs(_safe_float(row.get("residual")) or 0.0) for row in _prediction_rows(bundle)]
    residual_std = statistics.pstdev(residuals) if len(residuals) > 1 else (statistics.mean(residuals) if residuals else 0.0)
    final_forecast = bundle.get("finalForecast") or {}
    forecast_rows = final_forecast.get("forecast") if isinstance(final_forecast, dict) else None
    rows = [row for row in forecast_rows if isinstance(row, dict)] if isinstance(forecast_rows, list) else []
    if not rows:
        rows = [{"time": row.get("time"), "predicted": row.get("actual")} for row in _prediction_rows(bundle)[-7:]]
    median = []
    p10 = []
    p90 = []
    for row in rows:
        predicted = _safe_float(row.get("predicted")) or 0.0
        median.append({"time": row.get("time"), "value": round(predicted, 4)})
        p10.append({"time": row.get("time"), "value": round(predicted - residual_std, 4)})
        p90.append({"time": row.get("time"), "value": round(predicted + residual_std, 4)})
    return _artifact(kind="chart", title="Monte Carlo 概率带", summary="已用 residual 波动近似生成 P10 / P50 / P90 区间。", source_skill_id=source_skill_id, data={"chartType": "band_line", "median": median, "lower": p10, "upper": p90}, markdown="## Monte Carlo 概率带\n\n- 已用 residual 波动近似生成 P10 / P50 / P90 区间。", report_compatible=True)


def _rerun_restriction_artifact(skill_id: str, request: AgentRunRequest) -> AgentArtifact:
    return _artifact(
        kind="run_request",
        title="重跑动作受限",
        summary="当前版本不会在缺少源上传上下文时假装重跑。已返回一个可执行建议卡片。",
        source_skill_id=skill_id,
        data={
            "runnable": False,
            "reason": "missing_source_upload_context",
            "suggestion": "请在 /forecast 页面保留当前上传数据后再发起重跑类 Agent 动作，或先重新上传源文件。",
            "currentPage": request.currentPage,
        },
        markdown="## 重跑动作受限\n\n当前版本不会在缺少源上传上下文时假装重跑。请在 `/forecast` 页面保留当前上传数据后再发起重跑类 Agent 动作，或先重新上传源文件。",
        report_compatible=False,
    )


def _image_caption_artifact(*, scratch: dict[str, Any], source_skill_id: str) -> AgentArtifact:
    chart = scratch.get("latestChartArtifact")
    if not isinstance(chart, dict):
        summary = "当前还没有最新生成的图表 artifact，因此无法补充图片解读。"
        return _artifact(kind="warning", title="图片解读", summary=summary, source_skill_id=source_skill_id, data={}, markdown=f"## 图片解读\n\n{summary}")
    chart_type = str(chart.get("chartType") or "chart")
    summary = {
        "waterfall": "这张瀑布图强调了几个主要驱动项对结果变化的相对解释权重，适合管理层快速理解主要拉动与拖累因素。",
        "heatmap": "这张热力图展示了 residual 在周期格子中的分布强弱，有助于定位哪一类时间片更容易高估或低估。",
        "bubble": "这张气泡图同时比较了模型效果和耗时，越靠左且越靠下通常意味着更高的效率/效果平衡。",
        "multi_line": "这张情景图同时展示 baseline、upside、downside 三条路径，便于讨论目标区间。",
        "band_line": "这张概率带图把基于历史残差波动推导出的不确定区间可视化了。",
    }.get(chart_type, "这张图补充了当前实验的结构化视觉解释。")
    return _artifact(kind="markdown", title="图片解读", summary=summary, source_skill_id=source_skill_id, data={"chartType": chart_type}, markdown=f"## 图片解读\n\n{summary}", report_compatible=True)


def _executive_summary_artifact(bundle: dict[str, Any], *, scratch: dict[str, Any], request: AgentRunRequest, source_skill_id: str) -> AgentArtifact:
    largest = scratch.get("largestResidual")
    drivers = _driver_items(bundle)[:3]
    lines = [
        f"本次实验围绕“{request.prompt}”提取了 residual、特征解释和协变量策略三类证据。",
        (
            f"最大异常点在 {largest.get('time')}，残差 {(_safe_float(largest.get('residual')) or 0.0):.4f}。"
            if isinstance(largest, dict)
            else "当前没有明确的最大异常点记录。"
        ),
        (
            "主要驱动候选包括 " + "、".join(item["feature"] for item in drivers) + "。"
            if drivers
            else "当前没有足够的树模型驱动证据，建议结合 benchmark gap 与 residual 分析。"
        ),
    ]
    markdown = "## 管理层摘要\n\n" + "\n".join(f"- {line}" for line in lines)
    return _artifact(kind="markdown", title="管理层摘要", summary=lines[0], source_skill_id=source_skill_id, data={"lines": lines}, markdown=markdown, report_compatible=True)


def _artifact(
    *,
    kind: str,
    title: str,
    summary: str,
    source_skill_id: str,
    data: dict[str, Any],
    markdown: str | None = None,
    report_compatible: bool = False,
    downloadable: bool = False,
) -> AgentArtifact:
    return AgentArtifact(
        artifactId=f"aart_{uuid.uuid4().hex[:12]}",
        kind=kind,
        title=title,
        summary=summary,
        sourceSkillId=source_skill_id,
        createdAt=utc_iso(),
        markdown=markdown,
        reportCompatible=report_compatible,
        downloadable=downloadable,
        data=data,
    )


def _build_final_summary(scratch: dict[str, Any], bundle: dict[str, Any], *, request: AgentRunRequest) -> str:
    drivers = _driver_items(bundle)[:3]
    covariates = _covariates(bundle)
    fragments = [
        f"已围绕“{request.prompt}”完成本轮归因分析。",
        (
            "主要驱动候选：" + "、".join(item["feature"] for item in drivers) + "。"
            if drivers
            else "当前没有足够的树模型驱动证据，因此结论更多来自 residual / benchmark / covariate 策略。"
        ),
        (
            f"协变量风险项 {sum(1 for item in covariates if item.leakageRisk)} 个。"
            if covariates
            else "当前实验没有协变量风险项。"
        ),
    ]
    if scratch.get("latestReportSection"):
        fragments.append("已同步生成报告章节草稿。")
    if scratch.get("latestChartArtifact"):
        fragments.append("已生成可继续解读的图表 artifact。")
    return " ".join(fragments)


def _model_label(model_name: Any, model_id: Any) -> str:
    return str(model_name or model_id or "未知模型")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isfinite(number):
            return number
        return None
    except (TypeError, ValueError):
        return None


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _format_metric(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.4f}" if abs(number) < 1 else f"{number:.2f}"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
