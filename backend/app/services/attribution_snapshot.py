from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db.models import ExperimentRecord
from app.schemas import AttributionSnapshot, AttributionSnapshotSection
from app.services.explainability import load_experiment_explainability
from app.services.runtime_history import load_runtime_from_record


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(model: dict[str, Any], name: str) -> float | None:
    metrics = model.get("metrics") if isinstance(model, dict) else None
    if not isinstance(metrics, dict):
        return None
    return _safe_float(metrics.get(name))


def _model_name(model: dict[str, Any] | None) -> str:
    if not isinstance(model, dict):
        return "未知模型"
    return str(model.get("modelName") or model.get("modelId") or "未知模型")


def _residual_points(backtest: dict[str, Any], recommended_model_id: str | None) -> list[dict[str, Any]]:
    predictions = backtest.get("predictions") if isinstance(backtest, dict) else None
    if not isinstance(predictions, dict) or not recommended_model_id:
        return []
    rows = predictions.get(recommended_model_id)
    if not isinstance(rows, list):
        return []
    result = [row for row in rows if isinstance(row, dict)]
    result.sort(key=lambda row: abs(_safe_float(row.get("residual")) or 0.0), reverse=True)
    return result


def _top_drivers(model_logs: list[dict[str, Any]], experiment_id: str, recommended_model_id: str | None) -> list[dict[str, Any]]:
    explainability = load_experiment_explainability(
        experiment_id=experiment_id,
        recommended_model_id=recommended_model_id,
        model_logs=model_logs,
    )
    recommended = next((item for item in explainability.models if item.modelId == explainability.recommendedModelId), None)
    if recommended is None:
        recommended = explainability.models[0] if explainability.models else None
    if recommended is None:
        return []
    rows: list[dict[str, Any]] = []
    for item in recommended.shapTopFeatures[:6]:
        rows.append(
            {
                "feature": item.feature,
                "score": item.meanAbsShap,
                "direction": item.direction,
                "source": "shap",
            }
        )
    if rows:
        return rows
    for item in recommended.featureImportance[:6]:
        rows.append(
            {
                "feature": item.feature,
                "score": item.importance,
                "direction": item.direction,
                "source": "importance",
            }
        )
    return rows


def build_attribution_snapshot(record: ExperimentRecord) -> AttributionSnapshot:
    ranked_models = _loads(record.metrics_json, [])
    backtest = _loads(record.backtest_json, {})
    diagnostics = _loads(record.diagnostics_json, {})
    model_logs = _loads(record.model_logs_json, [])
    runtime = load_runtime_from_record(record)
    created_at = record.created_at.astimezone(timezone.utc).isoformat() if record.created_at else datetime.now(timezone.utc).isoformat()

    best_model = next((model for model in ranked_models if isinstance(model, dict) and model.get("rank") == 1), None)
    runner_up = next((model for model in ranked_models if isinstance(model, dict) and model.get("rank") == 2), None)
    best_mae = _metric(best_model, "mae")
    runner_up_mae = _metric(runner_up, "mae")
    residual_points = _residual_points(backtest, record.recommended_model_id)
    largest_residual = residual_points[0] if residual_points else None
    top_drivers = _top_drivers(model_logs, record.id, record.recommended_model_id)

    covariate_highlights: list[dict[str, Any]] = []
    if runtime is not None:
        for target in runtime.featurePipeline[:1]:
            for covariate in target.covariates[:8]:
                covariate_highlights.append(
                    {
                        "name": covariate.name,
                        "type": covariate.type,
                        "backtestStrategy": covariate.backtestStrategy,
                        "forecastStrategy": covariate.forecastStrategy,
                        "leakageRisk": covariate.leakageRisk,
                        "note": covariate.note,
                    }
                )

    warnings = [str(item) for item in diagnostics.get("warnings") or [] if item]
    if not top_drivers:
        warnings.append("当前实验缺少可直接回放的驱动排序证据，Agent 会优先走 residual / benchmark 分析。")

    overview_summary = [
        f"当前推荐模型为 {_model_name(best_model)}，最佳 MAE 为 {best_mae:.4f}。" if best_mae is not None else f"当前推荐模型为 {_model_name(best_model)}。",
        (
            f"第二名 {_model_name(runner_up)} 的 MAE 为 {runner_up_mae:.4f}，与推荐模型的差值为 {(runner_up_mae - best_mae):.4f}。"
            if best_mae is not None and runner_up_mae is not None and runner_up is not None
            else "当前没有完整的 runner-up 指标，建议先看模型对比与 runtime 轨迹。"
        ),
        f"实验目标列为 {record.target_column}，历史实验可以继续做图表、归因和报告补充。",
    ]

    quick_diagnosis_summary = [
        (
            f"最大残差点出现在 {largest_residual.get('time')}，实际值 {largest_residual.get('actual')}，预测值 {largest_residual.get('predicted')}，Residual {largest_residual.get('residual')}。"
            if largest_residual
            else "当前没有可定位的最大残差点。"
        ),
        (
            f"已回放出 {len(top_drivers)} 个主要驱动候选，可直接让 Agent 生成瀑布图或管理层摘要。"
            if top_drivers
            else "当前缺少树模型驱动排序，建议先做 benchmark gap / anomaly 角度的解释。"
        ),
    ]

    anomaly_summary = [
        f"诊断中记录了 {diagnostics.get('outlierCount', 0)} 个异常候选，实际调整 {diagnostics.get('outlierAdjustedCount', 0)} 个。",
        f"缺失时间点 {diagnostics.get('missingTimeCount', 0)}，重复时间点 {diagnostics.get('duplicateTimeCount', 0)}。",
        "如果要继续看异常阶段的解释证据，Agent 可以直接读取 residual、季节性和异常检测结果。",
    ]

    deep_attribution_summary = [
        (
            "主要驱动候选：" + "、".join(
                f"{item['feature']} ({item['source']}={_format_score(item.get('score'))})"
                for item in top_drivers[:5]
            )
            if top_drivers
            else "当前没有直接持久化的 feature importance / SHAP 驱动证据。"
        ),
        (
            f"协变量路径里共有 {len(covariate_highlights)} 个重点项，其中泄漏风险项 {sum(1 for item in covariate_highlights if item.get('leakageRisk'))} 个。"
            if covariate_highlights
            else "当前实验未登记协变量路径或没有启用协变量。"
        ),
    ]

    scenario_summary = [
        "Agent 可以基于当前实验生成情景分析、Monte Carlo、瀑布图、热力图和管理层版本摘要。",
        "重跑类动作会先检查当前实验是否仍保留足够的源上下文，避免假执行。",
    ]

    return AttributionSnapshot(
        experimentId=record.id,
        updatedAt=created_at,
        overview=AttributionSnapshotSection(
            title="Overview",
            summary=overview_summary,
            highlights=[
                {"label": "recommendedModel", "value": record.recommended_model_id},
                {"label": "bestMae", "value": best_mae},
                {"label": "runnerUpMae", "value": runner_up_mae},
            ],
            askAgentPrompts=[
                "这次最主要的下降原因是什么？",
                "给我一个面向管理层的结果摘要。",
            ],
        ),
        quickDiagnosis=AttributionSnapshotSection(
            title="Quick Diagnosis",
            summary=quick_diagnosis_summary,
            highlights=([largest_residual] if largest_residual else []),
            askAgentPrompts=[
                "解释这个实验里最大的异常点。",
                "把主要问题按优先级排一下。",
            ],
        ),
        anomalyResidualLab=AttributionSnapshotSection(
            title="Anomaly & Residual Lab",
            summary=anomaly_summary,
            highlights=residual_points[:5],
            askAgentPrompts=[
                "做一次异常检测并解释异常点。",
                "只看 residual pattern，判断高估还是低估偏多。",
            ],
        ),
        deepAttribution=AttributionSnapshotSection(
            title="Deep Attribution",
            summary=deep_attribution_summary,
            highlights=top_drivers + covariate_highlights[:4],
            askAgentPrompts=[
                "生成一张管理层可看的瀑布图。",
                "把协变量泄漏风险单独总结出来。",
            ],
        ),
        scenarioExecutiveOutput=AttributionSnapshotSection(
            title="Scenario & Executive Output",
            summary=scenario_summary,
            highlights=covariate_highlights[:6],
            askAgentPrompts=[
                "做一个上下行情景分析。",
                "把上面的结论写成报告段落。",
            ],
        ),
        warnings=warnings,
    )


def load_attribution_snapshot(record: ExperimentRecord) -> AttributionSnapshot:
    if record.attribution_json:
        try:
            return AttributionSnapshot.model_validate(_loads(record.attribution_json, {}))
        except Exception:
            pass
    return build_attribution_snapshot(record)


def _format_score(value: Any) -> str:
    score = _safe_float(value)
    if score is None:
        return "-"
    return f"{score:.4f}" if score < 1 else f"{score:.2f}"
