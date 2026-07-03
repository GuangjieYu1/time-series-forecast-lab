from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.errors import AppError
from app.schemas import DeepSeekConnectionResponse, ReportOptions
from app.services.auto_tuning.service import describe_tuning_profile
from app.services.model_registry import MODEL_CAPABILITIES


FEATURE_FAMILY_LABELS = {
    "lagFeatures": "Lag features",
    "rollingFeatures": "Rolling statistics",
    "calendarFeatures": "Calendar features",
    "covariates": "Covariates",
}

FEATURE_MODEL_IDS = {model_id for model_id, capability in MODEL_CAPABILITIES.items() if capability.supportsCovariates}


def _endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _sanitize_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "连接超时，请检查网络或稍后重试。"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"DeepSeek 返回 HTTP {exc.response.status_code}，请检查 API Key、模型名称或账户额度。"
    if isinstance(exc, httpx.RequestError):
        return "无法连接 DeepSeek，请检查 Base URL 或网络连接。"
    return "DeepSeek 调用失败，请检查 API Key、模型名称、余额或网络连接。"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _model_sort_key(model: dict[str, Any]) -> tuple[float, float, str]:
    metrics = _as_dict(model.get("metrics"))
    mae = _safe_float(metrics.get("mae"))
    rank = _safe_float(model.get("rank"))
    return (
        mae if mae is not None else float("inf"),
        rank if rank is not None else float("inf"),
        str(model.get("modelId") or ""),
    )


def _model_display_name(model: dict[str, Any]) -> str:
    return str(model.get("modelName") or model.get("modelId") or "unknown")


def _join_inline(items: list[str], empty: str = "无") -> str:
    filtered = [item for item in items if item]
    return "、".join(filtered) if filtered else empty


def _window_label(start: Any, end: Any) -> str:
    if start and end:
        return f"{start} → {end}"
    if start:
        return str(start)
    if end:
        return str(end)
    return "—"


def _format_model_ref(model: dict[str, Any] | None) -> str:
    if not model:
        return "—"
    return f"{_model_display_name(model)} (`{model.get('modelId') or 'unknown'}`)"


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _compact_time_label(value: Any) -> str:
    if value is None:
        return "—"
    text = str(value).replace("T", " ")
    return text[:16] if len(text) >= 16 else text


def test_deepseek_connection(api_key: str, base_url: str, model: str) -> DeepSeekConnectionResponse:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个连接测试助手，只需简短回答。"},
            {"role": "user", "content": "请回复：连接成功。"},
        ],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(_endpoint(base_url), headers=_headers(api_key), json=payload)
            response.raise_for_status()
        return DeepSeekConnectionResponse(success=True, model=model, message="连接成功")
    except Exception as exc:
        return DeepSeekConnectionResponse(
            success=False,
            model=model,
            message=_sanitize_error(exc),
            code="DEEPSEEK_CONNECT_FAILED",
        )


def build_report_context(experiment: dict[str, Any]) -> dict[str, Any]:
    ranked_models = experiment.get("rankedModels", [])
    diagnostics = experiment.get("diagnostics", {})
    backtest = experiment.get("backtest", {})
    final_forecast = experiment.get("finalForecast")
    predictions = backtest.get("predictions", {}) if isinstance(backtest, dict) else {}

    top_residuals: list[dict[str, Any]] = []
    for model in ranked_models:
        if model.get("status") != "success":
            continue
        model_id = model.get("modelId")
        rows = predictions.get(model_id, []) if isinstance(predictions, dict) else []
        for point in rows:
            top_residuals.append(
                {
                    "modelId": model_id,
                    "time": point.get("time"),
                    "actual": point.get("actual"),
                    "predicted": point.get("predicted"),
                    "residual": point.get("residual"),
                    "absoluteError": point.get("absoluteError"),
                }
            )
    top_residuals.sort(key=lambda item: abs(float(item.get("residual") or 0)), reverse=True)
    targets = _build_target_context(experiment)
    feature_pipeline = _build_feature_pipeline_summary(experiment, targets)
    runtime_summary = _build_runtime_summary(experiment)
    workflow_report = _build_workflow_report(experiment, targets, runtime_summary)
    model_recommendation = _build_model_recommendation_summary(experiment, targets, feature_pipeline)
    auto_tuning = _build_auto_tuning_summary(experiment, targets)
    chart_insights = _build_chart_insights(experiment, ranked_models, predictions, final_forecast)

    return {
        "experiment": {
            "experimentId": experiment.get("experimentId"),
            "experimentName": experiment.get("experimentName"),
            "fileName": experiment.get("fileName"),
            "sheetName": experiment.get("sheetName"),
            "targetColumn": experiment.get("targetColumn"),
            "recommendedModelId": experiment.get("recommendedModelId"),
            "bestMae": experiment.get("bestMae"),
            "createdAt": experiment.get("createdAt"),
        },
        "config": experiment.get("config", {}),
        "diagnostics": diagnostics,
        "dataHealth": experiment.get("dataHealth"),
        "rankedModels": ranked_models,
        "targets": targets,
        "featurePipeline": feature_pipeline,
        "runtimeSummary": runtime_summary,
        "workflowReport": workflow_report,
        "modelRecommendation": model_recommendation,
        "autoTuning": auto_tuning,
        "chartInsights": chart_insights,
        "topResidualPoints": top_residuals[:12],
        "finalForecastSummary": _forecast_summary(final_forecast),
        "modelLogs": experiment.get("modelLogs", []),
    }


def _build_chart_insights(
    experiment: dict[str, Any],
    ranked_models: list[dict[str, Any]],
    predictions: dict[str, Any],
    final_forecast: Any,
) -> dict[str, Any]:
    successful_models = [model for model in ranked_models if isinstance(model, dict) and model.get("status") == "success"]
    successful_models.sort(key=_model_sort_key)
    best_model = successful_models[0] if successful_models else None
    runner_up = successful_models[1] if len(successful_models) > 1 else None
    best_rows = (
        [row for row in _as_list(predictions.get(best_model.get("modelId"))) if isinstance(row, dict)]
        if best_model and isinstance(predictions, dict)
        else []
    )
    largest_residual = (
        max(best_rows, key=lambda row: abs(_safe_float(row.get("residual")) or 0.0))
        if best_rows
        else None
    )
    positive_residual_count = sum(1 for row in best_rows if (_safe_float(row.get("residual")) or 0.0) > 0)
    negative_residual_count = sum(1 for row in best_rows if (_safe_float(row.get("residual")) or 0.0) < 0)
    residual_prefix = best_rows[: max(1, len(best_rows) // 3)]
    residual_suffix = best_rows[-max(1, len(best_rows) // 3) :] if best_rows else []
    final_points = [point for point in _as_list(_as_dict(final_forecast).get("forecast")) if isinstance(point, dict)]
    interval_widths = [
        (_safe_float(point.get("upper")) or 0.0) - (_safe_float(point.get("lower")) or 0.0)
        for point in final_points
        if _safe_float(point.get("upper")) is not None and _safe_float(point.get("lower")) is not None
    ]
    return {
        "backtestCurve": {
            "bestModelId": best_model.get("modelId") if best_model else None,
            "bestModelName": _model_display_name(best_model) if best_model else None,
            "runnerUpModelName": _model_display_name(runner_up) if runner_up else None,
            "bestMae": _safe_float(_as_dict(best_model.get("metrics")).get("mae")) if best_model else None,
            "runnerUpMae": _safe_float(_as_dict(runner_up.get("metrics")).get("mae")) if runner_up else None,
            "largestResidualPoint": (
                {
                    "time": largest_residual.get("time"),
                    "actual": largest_residual.get("actual"),
                    "predicted": largest_residual.get("predicted"),
                    "residual": largest_residual.get("residual"),
                }
                if largest_residual
                else None
            ),
        },
        "residualPattern": {
            "positiveResidualCount": positive_residual_count,
            "negativeResidualCount": negative_residual_count,
            "prefixResidualMean": _average([
                _safe_float(row.get("residual")) or 0.0 for row in residual_prefix if _safe_float(row.get("residual")) is not None
            ]),
            "suffixResidualMean": _average([
                _safe_float(row.get("residual")) or 0.0 for row in residual_suffix if _safe_float(row.get("residual")) is not None
            ]),
            "meanAbsoluteError": _average([
                _safe_float(row.get("absoluteError")) or 0.0 for row in best_rows if _safe_float(row.get("absoluteError")) is not None
            ]),
        },
        "metricRanking": [
            {
                "modelId": model.get("modelId"),
                "modelName": _model_display_name(model),
                "rank": model.get("rank"),
                "mae": _safe_float(_as_dict(model.get("metrics")).get("mae")),
                "rmse": _safe_float(_as_dict(model.get("metrics")).get("rmse")),
                "wape": _safe_float(_as_dict(model.get("metrics")).get("wape")),
            }
            for model in successful_models[:6]
        ],
        "finalForecastChart": {
            "modelName": _as_dict(final_forecast).get("modelInfo", {}).get("name") if isinstance(_as_dict(final_forecast).get("modelInfo"), dict) else None,
            "horizon": len(final_points),
            "firstPoint": final_points[0] if final_points else None,
            "lastPoint": final_points[-1] if final_points else None,
            "averageIntervalWidth": _average(interval_widths),
        },
        "narrativeHints": [
            (
                f"回测对比图里，{_model_display_name(best_model)} 是当前推荐模型，MAE 为 {_format_metric(_safe_float(_as_dict(best_model.get('metrics')).get('mae')))}。"
                if best_model
                else "当前没有成功模型，因此回测对比图只能用于解释失败情况和数据风险。"
            ),
            (
                f"最大残差出现在 {_compact_time_label(largest_residual.get('time'))}，Residual={_format_metric(_safe_float(largest_residual.get('residual')))}。"
                if largest_residual
                else "当前没有可用的最大残差定位点。"
            ),
            (
                f"Residual 时间线中，正残差 {positive_residual_count} 个、负残差 {negative_residual_count} 个，可直接判断低估/高估偏向。"
                if best_rows
                else "当前没有足够的 residual 点来解释误差偏向。"
            ),
            (
                f"最终预测图显示未来 {len(final_points)} 个时间点，首尾预测值从 {_format_metric(_safe_float(final_points[0].get('predicted')))} 变化到 {_format_metric(_safe_float(final_points[-1].get('predicted')))}。"
                if len(final_points) >= 1
                else "当前还没有最终预测图。"
            ),
        ],
    }


def _build_target_context(experiment: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = experiment.get("manifest")
    manifest_targets = manifest.get("targets", []) if isinstance(manifest, dict) else []
    if manifest_targets:
        result = []
        for target in manifest_targets:
            result.append(
                {
                    "targetColumn": target.get("targetColumn"),
                    "detectedFrequency": target.get("detectedFrequency"),
                    "timeStart": target.get("timeStart"),
                    "timeEnd": target.get("timeEnd"),
                    "trainStart": target.get("trainStart"),
                    "trainEnd": target.get("trainEnd"),
                    "testStart": target.get("testStart"),
                    "testEnd": target.get("testEnd"),
                    "recommendedModelId": target.get("recommendedModelId"),
                    "models": [_compact_model_entry(model) for model in target.get("models", []) if isinstance(model, dict)],
                }
            )
        return result

    return [
        {
            "targetColumn": experiment.get("targetColumn"),
            "detectedFrequency": None,
            "timeStart": None,
            "timeEnd": None,
            "trainStart": None,
            "trainEnd": None,
            "testStart": None,
            "testEnd": None,
            "recommendedModelId": experiment.get("recommendedModelId"),
            "models": [_compact_model_entry(model) for model in experiment.get("rankedModels", []) if isinstance(model, dict)],
        }
    ]


def _build_feature_pipeline_summary(experiment: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
    config = _as_dict(experiment.get("config"))
    data_profile = _as_dict(experiment.get("dataProfile"))
    manifest = _as_dict(experiment.get("manifest"))
    manifest_data = _as_dict(manifest.get("data"))
    feature_config = _as_dict(data_profile.get("featureConfig") or config.get("featureConfig"))
    covariate_columns = _as_list(
        data_profile.get("covariateColumns")
        or config.get("covariateColumns")
        or manifest_data.get("covariateColumns")
    )
    enabled_feature_families = [
        label for key, label in FEATURE_FAMILY_LABELS.items() if bool(feature_config.get(key))
    ]
    disabled_feature_families = [
        label for key, label in FEATURE_FAMILY_LABELS.items() if not bool(feature_config.get(key))
    ]
    selected_model_ids = _as_list(config.get("selectedModels"))
    if not selected_model_ids:
        selected_model_ids = list(
            dict.fromkeys(
                model.get("modelId")
                for target in targets
                for model in _as_list(target.get("models"))
                if isinstance(model, dict) and model.get("modelId")
            )
        )
    feature_ready_models = [
        f"{MODEL_CAPABILITIES[model_id].name} ({model_id})"
        for model_id in selected_model_ids
        if model_id in MODEL_CAPABILITIES and MODEL_CAPABILITIES[model_id].supportsCovariates
    ]
    cleaning = _as_dict(data_profile.get("cleaning"))
    data_mode = str(data_profile.get("mode") or config.get("dataMode") or "unknown")
    aggregation = data_profile.get("aggregation")
    alignment_strategy = (
        "本次未选择协变量，特征管线只使用时间序列派生特征。"
        if not covariate_columns
        else "协变量先在同一时间桶内按均值聚合，再与目标序列按规则频率对齐；缺失值先前向/后向填充，仍为空时补 0。"
    )
    return {
        "dataMode": data_mode,
        "timeColumn": data_profile.get("timeColumn") or config.get("timeColumn") or manifest_data.get("timeColumn"),
        "targetColumns": [target.get("targetColumn") for target in targets if target.get("targetColumn")],
        "covariateColumns": covariate_columns,
        "enabledFeatureFamilies": enabled_feature_families,
        "disabledFeatureFamilies": disabled_feature_families,
        "featureReadyModels": feature_ready_models,
        "featureConfig": feature_config,
        "aggregation": aggregation,
        "detectedFrequency": data_profile.get("detectedFrequency"),
        "sourceFrequency": data_profile.get("sourceFrequency"),
        "historyPointCount": len(_as_list(data_profile.get("history"))),
        "covariatePointCount": len(_as_list(data_profile.get("covariateHistory"))),
        "cleaning": cleaning,
        "alignmentStrategy": alignment_strategy,
        "usesCovariates": bool(covariate_columns and feature_config.get("covariates", True)),
    }


def _build_runtime_summary(experiment: dict[str, Any]) -> dict[str, Any]:
    runtime = _as_dict(experiment.get("runtime"))
    if not runtime:
        return {}
    models = [item for item in _as_list(runtime.get("models")) if isinstance(item, dict)]
    optimization = [item for item in _as_list(runtime.get("optimization")) if isinstance(item, dict)]
    state_machine = [item for item in _as_list(runtime.get("stateMachine")) if isinstance(item, dict)]
    completed_stages = [str(step.get("label") or step.get("id")) for step in state_machine if step.get("status") == "completed"]
    return {
        "kind": runtime.get("kind"),
        "status": runtime.get("status"),
        "currentStage": runtime.get("currentStage"),
        "currentStageLabel": runtime.get("currentStageLabel"),
        "estimatedTotalSeconds": runtime.get("estimatedTotalSeconds"),
        "estimatedRemainingSeconds": runtime.get("estimatedRemainingSeconds"),
        "elapsedSeconds": runtime.get("elapsedSeconds"),
        "logCount": len(_as_list(runtime.get("logs"))),
        "timelineCount": len(_as_list(runtime.get("timeline"))),
        "featureTargetCount": len(_as_list(runtime.get("featurePipeline"))),
        "optimizationModelCount": len(optimization),
        "completedStages": completed_stages,
        "modelCount": len(models),
    }


def _build_workflow_report(
    experiment: dict[str, Any],
    targets: list[dict[str, Any]],
    runtime_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = _as_dict(experiment.get("config"))
    selected_models = _as_list(config.get("selectedModels"))
    if not selected_models:
        selected_models = list(
            dict.fromkeys(
                model.get("modelId")
                for target in targets
                for model in _as_list(target.get("models"))
                if isinstance(model, dict) and model.get("modelId")
            )
        )
    selected_model_names = [
        f"{MODEL_CAPABILITIES[model_id].name} ({model_id})"
        if model_id in MODEL_CAPABILITIES
        else str(model_id)
        for model_id in selected_models
    ]
    target_summaries: list[dict[str, Any]] = []
    success_count = 0
    failed_count = 0
    for target in targets:
        models = [model for model in _as_list(target.get("models")) if isinstance(model, dict)]
        successful_models = [_model_display_name(model) for model in models if model.get("status") == "success"]
        failed_models = [_model_display_name(model) for model in models if model.get("status") == "failed"]
        success_count += len(successful_models)
        failed_count += len(failed_models)
        target_summaries.append(
            {
                "targetColumn": target.get("targetColumn"),
                "detectedFrequency": target.get("detectedFrequency"),
                "trainWindow": _window_label(target.get("trainStart"), target.get("trainEnd")),
                "testWindow": _window_label(target.get("testStart"), target.get("testEnd")),
                "recommendedModelId": target.get("recommendedModelId"),
                "successfulModels": successful_models,
                "failedModels": failed_models,
            }
        )
    return {
        "targetCount": len(targets),
        "modelCount": len(selected_models),
        "modelRunCount": sum(len(_as_list(target.get("models"))) for target in targets),
        "successfulModelRuns": success_count,
        "failedModelRuns": failed_count,
        "selectedModels": selected_models,
        "selectedModelNames": selected_model_names,
        "horizon": config.get("horizon"),
        "testSize": config.get("testSize"),
        "holdoutPolicy": f"最后 {config.get('testSize')} 个时间点作为 Holdout。" if config.get("testSize") else None,
        "runProfile": config.get("runProfile"),
        "parameterStrategy": config.get("parameterStrategy"),
        "randomSeed": config.get("randomSeed"),
        "finalForecastGenerated": bool(experiment.get("finalForecast")),
        "runtimeStatus": _as_dict(runtime_summary).get("status"),
        "runtimeStage": _as_dict(runtime_summary).get("currentStageLabel"),
        "runtimeElapsedSeconds": _as_dict(runtime_summary).get("elapsedSeconds"),
        "runtimeEstimatedTotalSeconds": _as_dict(runtime_summary).get("estimatedTotalSeconds"),
        "runtimeCompletedStages": _as_dict(runtime_summary).get("completedStages", []),
        "targets": target_summaries,
    }


def _build_model_recommendation_summary(
    experiment: dict[str, Any],
    targets: list[dict[str, Any]],
    feature_pipeline: dict[str, Any],
) -> dict[str, Any]:
    recommendations: list[dict[str, Any]] = []
    uses_covariates = bool(feature_pipeline.get("usesCovariates"))
    enabled_features = _as_list(feature_pipeline.get("enabledFeatureFamilies"))
    for target in targets:
        models = [model for model in _as_list(target.get("models")) if isinstance(model, dict)]
        successful_models = [model for model in models if model.get("status") == "success"]
        successful_models.sort(key=_model_sort_key)
        recommended_model_id = target.get("recommendedModelId")
        recommended_model = next((model for model in models if model.get("modelId") == recommended_model_id), None)
        if recommended_model is None and successful_models:
            recommended_model = successful_models[0]
            recommended_model_id = recommended_model.get("modelId")
        runner_up = next(
            (
                model
                for model in successful_models
                if recommended_model and model.get("modelId") != recommended_model.get("modelId")
            ),
            None,
        )
        reasons: list[str] = []
        caveats: list[str] = []
        if recommended_model is None:
            caveats.append("该目标列没有成功模型，因此当前没有可靠推荐。")
        else:
            metrics = _as_dict(recommended_model.get("metrics"))
            mae = _safe_float(metrics.get("mae"))
            rmse = _safe_float(metrics.get("rmse"))
            wape = _safe_float(metrics.get("wape"))
            if mae is not None:
                reasons.append(f"在成功模型中 MAE 最低，为 {mae:.4f}。")
            if rmse is not None:
                reasons.append(f"RMSE 为 {rmse:.4f}，可作为误差波动量级的补充参考。")
            if wape is not None:
                reasons.append(f"WAPE 为 {wape:.4f}，说明相对误差处于可对比区间。")
            if runner_up is not None:
                runner_mae = _safe_float(_as_dict(runner_up.get("metrics")).get("mae"))
                if mae is not None and runner_mae is not None:
                    gap = runner_mae - mae
                    if gap > 0:
                        reasons.append(f"相比第二名 {_model_display_name(runner_up)}，MAE 再下降 {gap:.4f}。")
                    elif gap == 0:
                        caveats.append(f"与第二名 {_model_display_name(runner_up)} 的 MAE 持平，建议结合业务可解释性一起判断。")
            tuning = _as_dict(recommended_model.get("tuning"))
            if tuning and (tuning.get("enabled") or tuning.get("strategy") == "auto"):
                reasons.append(
                    f"该模型经历了自动优化，共评估 {tuning.get('candidateCount', 0)} 个候选，最终最佳 MAE 为 {_format_metric(tuning.get('bestMetric'))}。"
                )
            elif tuning:
                reasons.append("该模型未启用自动优化，沿用了默认参数或手动高级参数。")
            if uses_covariates and recommended_model.get("modelId") in FEATURE_MODEL_IDS:
                reasons.append(f"该模型可直接消费已启用的特征管线：{_join_inline(enabled_features)}。")
            warnings = [str(warning) for warning in _as_list(recommended_model.get("warnings")) if warning]
            if warnings:
                caveats.extend(warnings[:3])
        recommendations.append(
            {
                "targetColumn": target.get("targetColumn"),
                "recommendedModelId": recommended_model_id,
                "recommendedModelName": _model_display_name(recommended_model) if recommended_model else None,
                "runnerUpModelId": runner_up.get("modelId") if runner_up else None,
                "runnerUpModelName": _model_display_name(runner_up) if runner_up else None,
                "maeGapVsRunnerUp": (
                    None
                    if recommended_model is None or runner_up is None
                    else (
                        (_safe_float(_as_dict(runner_up.get("metrics")).get("mae")) or 0.0)
                        - (_safe_float(_as_dict(recommended_model.get("metrics")).get("mae")) or 0.0)
                    )
                ),
                "bestMetrics": _as_dict(recommended_model.get("metrics")) if recommended_model else {},
                "tuning": _as_dict(recommended_model.get("tuning")) if recommended_model else {},
                "reasons": reasons,
                "caveats": caveats,
            }
        )
    return {
        "experimentRecommendedModelId": experiment.get("recommendedModelId"),
        "recommendations": recommendations,
    }


def _compact_model_entry(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelId": model.get("modelId"),
        "modelName": model.get("modelName"),
        "rank": model.get("rank"),
        "status": model.get("status"),
        "metrics": model.get("metrics"),
        "runtime": model.get("runtime"),
        "warnings": model.get("warnings", []),
        "error": model.get("error"),
        "tuning": _compact_tuning(model.get("tuning")),
    }


def _compact_tuning(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "enabled": bool(value.get("enabled")),
        "profile": value.get("profile"),
        "strategy": value.get("strategy"),
        "strategyLabel": value.get("strategyLabel"),
        "sampler": value.get("sampler"),
        "pruner": value.get("pruner"),
        "selectedParams": value.get("selectedParams", {}),
        "candidateCount": value.get("candidateCount", 0),
        "bestMetric": value.get("bestMetric"),
        "tuningSeconds": value.get("tuningSeconds", 0.0),
        "candidateLimit": value.get("candidateLimit", 0),
        "timeBudgetSeconds": value.get("timeBudgetSeconds", 0.0),
        "validationSize": value.get("validationSize", 0),
        "stoppedEarly": bool(value.get("stoppedEarly")),
        "warnings": value.get("warnings", []),
        "trials": [
            {
                "round": trial.get("round"),
                "params": trial.get("params", {}),
                "status": trial.get("status"),
                "metrics": trial.get("metrics"),
                "elapsedSeconds": trial.get("elapsedSeconds", 0.0),
                "selected": bool(trial.get("selected")),
                "message": trial.get("message"),
            }
            for trial in value.get("trials", [])
            if isinstance(trial, dict)
        ],
    }


def _build_auto_tuning_summary(experiment: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
    config = experiment.get("config", {})
    parameter_strategy = str(config.get("parameterStrategy") or "default")
    run_profile = str(config.get("runProfile") or "balanced")
    profile = describe_tuning_profile(run_profile)
    runtime = _as_dict(experiment.get("runtime"))
    runtime_optimization = [item for item in _as_list(runtime.get("optimization")) if isinstance(item, dict)]
    runtime_strategies = {
        f"{item.get('targetColumn')}::{item.get('modelId')}": {
            "strategyLabel": item.get("strategyLabel"),
            "sampler": item.get("sampler"),
            "pruner": item.get("pruner"),
            "status": item.get("status"),
            "currentTrial": item.get("currentTrial"),
            "totalTrials": item.get("totalTrials"),
            "bestMetric": item.get("bestMetric"),
            "currentMetric": item.get("currentMetric"),
            "selectedParams": item.get("selectedParams", {}),
            "warnings": item.get("warnings", []),
        }
        for item in runtime_optimization
    }

    tuning_models = 0
    trial_count = 0
    for target in targets:
        for model in target.get("models", []):
            tuning = model.get("tuning")
            if not tuning:
                continue
            if tuning.get("strategy") == "auto" or tuning.get("enabled"):
                tuning_models += 1
            trial_count += len(tuning.get("trials", []))

    return {
        "enabled": parameter_strategy == "auto",
        "parameterStrategy": parameter_strategy,
        "runProfile": run_profile,
        "candidateLimitPerModel": int(profile["candidateLimit"]) if parameter_strategy == "auto" else 1,
        "timeBudgetSecondsPerModel": float(profile["timeBudgetSeconds"]) if parameter_strategy == "auto" else 0.0,
        "tuningModelCount": tuning_models,
        "trialCount": trial_count,
        "targetCount": len(targets),
        "runtimeOptimizationModelCount": len(runtime_optimization),
        "runtimeStrategies": runtime_strategies,
    }


def _forecast_summary(final_forecast: dict[str, Any] | None) -> dict[str, Any] | None:
    if not final_forecast:
        return None
    forecast = final_forecast.get("forecast", [])
    if not forecast:
        return None
    values = [float(point["predicted"]) for point in forecast if point.get("predicted") is not None]
    if not values:
        return None
    return {
        "finalModelId": final_forecast.get("finalModelId"),
        "modelInfo": final_forecast.get("modelInfo"),
        "horizon": len(forecast),
        "firstPoint": forecast[0],
        "lastPoint": forecast[-1],
        "minPredicted": min(values),
        "maxPredicted": max(values),
        "averagePredicted": sum(values) / len(values),
        "hasInterval": any(point.get("lower") is not None or point.get("upper") is not None for point in forecast),
    }


def build_report_prompt(context: dict[str, Any], options: ReportOptions) -> list[dict[str, str]]:
    compact_context = json.dumps(context, ensure_ascii=False, indent=2)
    required_sections: list[str] = []
    if options.includeFeaturePipeline:
        required_sections.append("特征管线（Feature Pipeline）：说明 featureConfig、covariates、聚合/对齐/补值策略，以及哪些模型会消费这些特征。")
    if options.includeWorkflowReport:
        required_sections.append("实验工作流（Workflow Report）：说明数据模式、频率、Holdout 切分、run profile、自动优化开关，以及最终预测是否已生成。")
    required_sections.append("运行时透明度摘要：说明状态机、关键阶段、总耗时/预计耗时以及当前或历史 runtime 轨迹。")
    required_sections.append("数据健康与清洁概览。")
    if options.includeModelComparison:
        required_sections.append("模型对比结论。")
    required_sections.append("自动优化策略说明（如果本次开启了自动优化）。")
    required_sections.append("参数变化与结果变化分析。")
    required_sections.append("图像与图表解读：解释回测对比图、指标柱状图、残差图以及最终预测图分别说明了什么。")
    if options.includeModelRecommendation:
        required_sections.append("模型推荐结论：单独解释为什么推荐当前模型，并与第二名或主要备选模型比较。")
    if options.includeResidualAnalysis:
        required_sections.append("残差分析。")
    if options.includeFinalForecast:
        required_sections.append("最终预测结果。")
    required_sections.extend(["业务解释。", "建议。", "风险与限制。"])
    section_lines = "\n".join(f"{index}. {section}" for index, section in enumerate(required_sections, start=1))
    system = (
        "你是资深时间序列预测分析师。请基于给定实验摘要生成中文 Markdown 报告。"
        "不要声称看过原始文件或完整业务明细；只使用摘要、指标、残差、调参记录和预测结果。"
        "残差定义必须保持为 residual = actual - predicted。"
        "如果启用了自动优化，必须解释优化策略、候选参数变化与指标变化的关系，以及最终参数为何被选中。"
        "如果上下文里提供了 featurePipeline、workflowReport、runtimeSummary、modelRecommendation、chartInsights，请在正文中准确引用。"
    )
    user = f"""
请生成一份{options.style}风格、{options.length}长度的中文时间序列预测分析报告。

报告必须包含：
{section_lines}

写作要求：
- 使用 Markdown，并优先使用二级、三级标题组织结构。
- 保留 MAE、MSE、RMSE、WAPE、Residual、Holdout 等术语，并给中文解释。
- 明确说明 residual = actual - predicted，正残差代表模型低估，负残差代表模型高估。
- 如果提供了 Data Health，请解释健康分、关键 warnings，以及这些问题如何影响模型可信度。
- 如果某些模型失败，要解释为单模型失败，不影响其他模型比较。
- 如果有自动调参记录，要分析候选参数如何影响 MAE / RMSE / WAPE，并解释最终选型逻辑。
- 如果上下文提供了模型推荐摘要，要解释推荐模型、第二名、MAE 差值、是否使用自动优化，以及启用的特征管线如何影响最终推荐。
- 如果上下文提供了 chartInsights，要把“图中说明了什么”写清楚，尤其是回测对比图、残差图和最终预测图，不要只复述有图这一事实。
- 如果上下文提供了 feature pipeline / workflow / runtime summary，请把它们写成正文独立小节，而不是只在结尾一笔带过。
- 可以使用 Markdown 表格总结关键候选，但不要把整段 JSON 原样重复到正文里。
- 不要输出 API Key、不要编造不存在的原始明细。
- 如果某个可选章节未开启，就不要输出该章节。

实验摘要如下：
```json
{compact_context}
```
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _report_max_tokens(length: str) -> int:
    if length == "long":
        return 4600
    if length == "medium":
        return 3200
    return 1800


def _request_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, str | None]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    with httpx.Client(timeout=90) as client:
        response = client.post(_endpoint(base_url), headers=_headers(api_key), json=payload)
        response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]
    content = choice["message"]["content"]
    finish_reason = choice.get("finish_reason")
    if not isinstance(content, str) or not content.strip():
        raise AppError("DeepSeek returned an empty report.", code="DEEPSEEK_EMPTY_REPORT")
    return content.strip(), finish_reason


def _overlap_size(left: str, right: str) -> int:
    max_size = min(len(left), len(right), 240)
    for size in range(max_size, 24, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


def _combine_chunks(chunks: list[str]) -> str:
    combined: list[str] = []
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        if not combined:
            combined.append(text)
            continue
        overlap = _overlap_size(combined[-1], text)
        if overlap:
            text = text[overlap:].lstrip()
        if text:
            combined.append(text)
    return "\n\n".join(combined).strip()


def _format_metric(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)


def _md_cell(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br/>")


def _build_feature_workflow_appendix(context: dict[str, Any], options: ReportOptions) -> str:
    lines: list[str] = []
    feature_pipeline = _as_dict(context.get("featurePipeline"))
    workflow_report = _as_dict(context.get("workflowReport"))
    runtime_summary = _as_dict(context.get("runtimeSummary"))

    if options.includeFeaturePipeline:
        covariates = [str(item) for item in _as_list(feature_pipeline.get("covariateColumns")) if item]
        enabled_features = [str(item) for item in _as_list(feature_pipeline.get("enabledFeatureFamilies")) if item]
        ready_models = [str(item) for item in _as_list(feature_pipeline.get("featureReadyModels")) if item]
        lines.extend(
            [
                "## 附录：Feature Pipeline",
                "",
                "### 配置摘要",
                "",
                f"- 数据模式：`{feature_pipeline.get('dataMode') or 'unknown'}`",
                f"- 时间列：`{feature_pipeline.get('timeColumn') or 'unknown'}`",
                f"- 目标列：{_join_inline([f'`{item}`' for item in _as_list(feature_pipeline.get('targetColumns')) if item], '无')}",
                f"- 协变量列：{_join_inline([f'`{item}`' for item in covariates], '未选择')}",
                f"- 启用特征族：{_join_inline(enabled_features, '未启用')}",
                f"- 关闭特征族：{_join_inline([str(item) for item in _as_list(feature_pipeline.get('disabledFeatureFamilies')) if item], '无')}",
                f"- 可直接消费这些特征的模型：{_join_inline(ready_models, '当前未选择特征模型')}",
                f"- 聚合 / 去重策略：`{feature_pipeline.get('aggregation') or 'none'}`",
                f"- 识别频率：`{feature_pipeline.get('detectedFrequency') or 'unknown'}`（源频率 `{feature_pipeline.get('sourceFrequency') or 'unknown'}`）",
                f"- 历史点数：{feature_pipeline.get('historyPointCount', 0)} / 协变量对齐点数：{feature_pipeline.get('covariatePointCount', 0)}",
                f"- 对齐策略：{feature_pipeline.get('alignmentStrategy') or '—'}",
                "",
                "原始 featureConfig：",
                "```json",
                json.dumps(_as_dict(feature_pipeline.get("featureConfig")), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
        cleaning = _as_dict(feature_pipeline.get("cleaning"))
        if cleaning:
            lines.extend(
                [
                    "清洗与补值配置：",
                    "```json",
                    json.dumps(cleaning, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

    if options.includeWorkflowReport:
        lines.extend(
            [
                "## 附录：Workflow Report",
                "",
                "### 运行摘要",
                "",
                f"- 目标列数量：{workflow_report.get('targetCount', 0)}",
                f"- 选择模型数量：{workflow_report.get('modelCount', 0)}",
                f"- 实际目标-模型组合：{workflow_report.get('modelRunCount', 0)}",
                f"- 成功组合：{workflow_report.get('successfulModelRuns', 0)}",
                f"- 失败组合：{workflow_report.get('failedModelRuns', 0)}",
                f"- 运行模式：`{workflow_report.get('runProfile') or 'balanced'}`",
                f"- 参数策略：`{workflow_report.get('parameterStrategy') or 'default'}`",
                f"- Holdout 策略：{workflow_report.get('holdoutPolicy') or '—'}",
                f"- 预测 Horizon：{workflow_report.get('horizon') or '—'}",
                f"- Test Size：{workflow_report.get('testSize') or '—'}",
                f"- 随机种子：{workflow_report.get('randomSeed') or '—'}",
                f"- 已生成最终预测：{'是' if workflow_report.get('finalForecastGenerated') else '否'}",
                f"- Runtime 状态：`{workflow_report.get('runtimeStatus') or 'unknown'}` / `{workflow_report.get('runtimeStage') or 'unknown'}`",
                f"- Runtime 已耗时：{_format_metric(workflow_report.get('runtimeElapsedSeconds'))} 秒",
                f"- Runtime 预计总时长：{_format_metric(workflow_report.get('runtimeEstimatedTotalSeconds'))} 秒",
                f"- 选择模型：{_join_inline([str(item) for item in _as_list(workflow_report.get('selectedModelNames')) if item], '无')}",
                "",
            ]
        )
        targets = [target for target in _as_list(workflow_report.get("targets")) if isinstance(target, dict)]
        if targets:
            lines.extend(
                [
                    "| 目标列 | 频率 | 训练窗口 | 测试窗口 | 成功模型 | 失败模型 | 推荐模型 |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for target in targets:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _md_cell(target.get("targetColumn") or "—"),
                            _md_cell(target.get("detectedFrequency") or "—"),
                            _md_cell(target.get("trainWindow") or "—"),
                            _md_cell(target.get("testWindow") or "—"),
                            _md_cell(_join_inline([str(item) for item in _as_list(target.get("successfulModels")) if item])),
                            _md_cell(_join_inline([str(item) for item in _as_list(target.get("failedModels")) if item], "无")),
                            _md_cell(target.get("recommendedModelId") or "—"),
                        ]
                    )
                    + " |"
                )
            lines.append("")

    if runtime_summary:
        lines.extend(
            [
                "## 附录：Runtime Summary",
                "",
                f"- 运行类型：`{runtime_summary.get('kind') or 'unknown'}`",
                f"- 最终状态：`{runtime_summary.get('status') or 'unknown'}`",
                f"- 当前/最终阶段：`{runtime_summary.get('currentStageLabel') or runtime_summary.get('currentStage') or 'unknown'}`",
                f"- 已耗时：{_format_metric(runtime_summary.get('elapsedSeconds'))} 秒",
                f"- 预计总时长：{_format_metric(runtime_summary.get('estimatedTotalSeconds'))} 秒",
                f"- Feature Pipeline 目标数：{runtime_summary.get('featureTargetCount', 0)}",
                f"- Optimization 模型数：{runtime_summary.get('optimizationModelCount', 0)}",
                f"- 日志条数：{runtime_summary.get('logCount', 0)} / Timeline 事件数：{runtime_summary.get('timelineCount', 0)}",
                f"- 已完成阶段：{_join_inline([str(item) for item in _as_list(runtime_summary.get('completedStages')) if item], '无')}",
                "",
            ]
        )

    return "\n".join(lines).strip()


def _build_recommendation_appendix(context: dict[str, Any], options: ReportOptions) -> str:
    if not options.includeModelRecommendation:
        return ""
    summary = _as_dict(context.get("modelRecommendation"))
    recommendations = [item for item in _as_list(summary.get("recommendations")) if isinstance(item, dict)]
    lines = [
        "## 附录：模型推荐依据",
        "",
        f"- 实验级推荐模型：`{summary.get('experimentRecommendedModelId') or '未产生'}`",
        "",
    ]
    if recommendations:
        lines.extend(
            [
                "| 目标列 | 推荐模型 | MAE | RMSE | WAPE | 第二名 | MAE 差值 | 调参候选 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in recommendations:
            metrics = _as_dict(item.get("bestMetrics"))
            tuning = _as_dict(item.get("tuning"))
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(item.get("targetColumn") or "—"),
                        _md_cell(item.get("recommendedModelName") or item.get("recommendedModelId") or "—"),
                        _md_cell(_format_metric(metrics.get("mae"))),
                        _md_cell(_format_metric(metrics.get("rmse"))),
                        _md_cell(_format_metric(metrics.get("wape"))),
                        _md_cell(item.get("runnerUpModelName") or item.get("runnerUpModelId") or "—"),
                        _md_cell(_format_metric(item.get("maeGapVsRunnerUp"))),
                        _md_cell(tuning.get("candidateCount", 0)),
                    ]
                )
                + " |"
            )
        lines.append("")

    for item in recommendations:
        lines.extend(
            [
                f"### 目标列：`{item.get('targetColumn') or 'unknown'}`",
                "",
                f"- 推荐模型：`{item.get('recommendedModelId') or '未产生'}` / {_md_cell(item.get('recommendedModelName') or '—')}",
                f"- 第二名：`{item.get('runnerUpModelId') or '—'}` / {_md_cell(item.get('runnerUpModelName') or '—')}",
                "",
                "推荐理由：",
            ]
        )
        reasons = [str(reason) for reason in _as_list(item.get("reasons")) if reason]
        if reasons:
            lines.extend([f"- {reason}" for reason in reasons])
        else:
            lines.append("- 暂无可解释推荐理由。")
        caveats = [str(caveat) for caveat in _as_list(item.get("caveats")) if caveat]
        if caveats:
            lines.extend(["", "注意事项："])
            lines.extend([f"- {caveat}" for caveat in caveats])
        lines.append("")

    return "\n".join(lines).strip()


def _build_visual_appendix(context: dict[str, Any], options: ReportOptions) -> str:
    chart_insights = _as_dict(context.get("chartInsights"))
    if not chart_insights:
        return ""
    lines = [
        "## 附录：图像与图表解读",
        "",
        "这些结论用于辅助前端回测对比图、指标柱状图、Residual 图和最终预测图的文字说明。",
        "",
    ]
    backtest_curve = _as_dict(chart_insights.get("backtestCurve"))
    residual_pattern = _as_dict(chart_insights.get("residualPattern"))
    final_chart = _as_dict(chart_insights.get("finalForecastChart"))
    metric_ranking = [item for item in _as_list(chart_insights.get("metricRanking")) if isinstance(item, dict)]
    hints = [str(item) for item in _as_list(chart_insights.get("narrativeHints")) if item]

    lines.extend(
        [
            "### 回测对比图",
            "",
            f"- 推荐模型：`{backtest_curve.get('bestModelId') or '未产生'}` / {_md_cell(backtest_curve.get('bestModelName') or '—')}",
            f"- 第二名：{_md_cell(backtest_curve.get('runnerUpModelName') or '—')}",
            f"- 推荐模型 MAE：{_format_metric(backtest_curve.get('bestMae'))}",
            f"- 第二名 MAE：{_format_metric(backtest_curve.get('runnerUpMae'))}",
            "",
        ]
    )
    largest_residual = _as_dict(backtest_curve.get("largestResidualPoint"))
    if largest_residual:
        lines.extend(
            [
                "最大残差点：",
                f"- 时间：`{_compact_time_label(largest_residual.get('time'))}`",
                f"- 实际值：{_format_metric(largest_residual.get('actual'))}",
                f"- 预测值：{_format_metric(largest_residual.get('predicted'))}",
                f"- Residual：{_format_metric(largest_residual.get('residual'))}",
                "",
            ]
        )

    lines.extend(
        [
            "### Residual 图",
            "",
            f"- 正残差数量：{residual_pattern.get('positiveResidualCount', 0)}",
            f"- 负残差数量：{residual_pattern.get('negativeResidualCount', 0)}",
            f"- 前段残差均值：{_format_metric(residual_pattern.get('prefixResidualMean'))}",
            f"- 后段残差均值：{_format_metric(residual_pattern.get('suffixResidualMean'))}",
            f"- 平均绝对误差：{_format_metric(residual_pattern.get('meanAbsoluteError'))}",
            "",
        ]
    )

    if metric_ranking:
        lines.extend(
            [
                "### 指标柱状图重点模型",
                "",
                "| 排名 | 模型 | MAE | RMSE | WAPE |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in metric_ranking:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(item.get("rank") or "—"),
                        _md_cell(item.get("modelName") or item.get("modelId") or "—"),
                        _md_cell(_format_metric(item.get("mae"))),
                        _md_cell(_format_metric(item.get("rmse"))),
                        _md_cell(_format_metric(item.get("wape"))),
                    ]
                )
                + " |"
            )
        lines.append("")

    if options.includeFinalForecast:
        lines.extend(
            [
                "### 最终预测图",
                "",
                f"- 最终模型：{_md_cell(final_chart.get('modelName') or '未生成')}",
                f"- 预测 Horizon：{final_chart.get('horizon', 0)}",
                f"- 首个预测点：{_md_cell(json.dumps(final_chart.get('firstPoint'), ensure_ascii=False) if final_chart.get('firstPoint') else '—')}",
                f"- 最后预测点：{_md_cell(json.dumps(final_chart.get('lastPoint'), ensure_ascii=False) if final_chart.get('lastPoint') else '—')}",
                f"- 平均区间宽度：{_format_metric(final_chart.get('averageIntervalWidth'))}",
                "",
            ]
        )

    if hints:
        lines.extend(["### 可直接写入正文的图像解读句子", ""])
        lines.extend([f"- {hint}" for hint in hints])
        lines.append("")

    return "\n".join(lines).strip()


def _build_tuning_appendix(context: dict[str, Any], options: ReportOptions) -> str:
    auto_tuning = context.get("autoTuning", {})
    targets = context.get("targets", [])
    runtime_strategies = _as_dict(auto_tuning.get("runtimeStrategies"))
    lines = [
        "## 附录：自动优化策略与逐轮结果",
        "",
        "### 策略摘要",
        "",
        f"- 参数策略：`{auto_tuning.get('parameterStrategy', 'default')}`",
        f"- 运行模式：`{auto_tuning.get('runProfile', 'balanced')}`",
        f"- 单模型候选上限：{auto_tuning.get('candidateLimitPerModel', 1)}",
        f"- 单模型时间预算：{_format_metric(auto_tuning.get('timeBudgetSecondsPerModel'))} 秒",
        f"- 记录到的调参模型数：{auto_tuning.get('tuningModelCount', 0)}",
        f"- 记录到的候选轮次数：{auto_tuning.get('trialCount', 0)}",
        "",
    ]

    if not auto_tuning.get("enabled"):
        lines.extend(
            [
                "本次实验未开启自动优化；各模型直接使用运行配置中的默认参数或高级设置参数。",
                "",
            ]
        )
        return "\n".join(lines).strip()

    if not targets:
        lines.extend(["暂无目标列级别的自动优化明细。", ""])
        return "\n".join(lines).strip()

    for target in targets:
        target_column = target.get("targetColumn") or "unknown"
        lines.extend(
            [
                f"### 目标列：`{target_column}`",
                "",
                f"- 推荐模型：`{target.get('recommendedModelId') or '未产生'}`",
                f"- 识别频率：`{target.get('detectedFrequency') or '未知'}`",
                "",
            ]
        )
        for model in target.get("models", []):
            tuning = model.get("tuning")
            runtime_strategy = _as_dict(runtime_strategies.get(f"{target_column}::{model.get('modelId')}"))
            lines.extend(
                [
                    f"#### {model.get('modelName') or model.get('modelId') or '模型'} (`{model.get('modelId') or 'unknown'}`)",
                    "",
                    f"- 状态：`{model.get('status') or 'unknown'}`",
                    f"- 排名：{model.get('rank') if model.get('rank') is not None else '未排名'}",
                    f"- MAE：{_format_metric((model.get('metrics') or {}).get('mae') if isinstance(model.get('metrics'), dict) else None)}",
                    f"- RMSE：{_format_metric((model.get('metrics') or {}).get('rmse') if isinstance(model.get('metrics'), dict) else None)}",
                ]
            )

            if not tuning:
                lines.extend(["- 未记录自动优化明细。", ""])
                continue

            lines.extend(
                [
                    f"- 调参策略：`{runtime_strategy.get('strategyLabel') or tuning.get('strategy') or 'default'}` / `profile={tuning.get('profile') or 'balanced'}`",
                    f"- Sampler：`{runtime_strategy.get('sampler') or '—'}` / Pruner：`{runtime_strategy.get('pruner') or '—'}`",
                    f"- 已评估候选：{tuning.get('candidateCount', 0)} / 上限 {tuning.get('candidateLimit', 0)}",
                    f"- 调参耗时：{_format_metric(tuning.get('tuningSeconds'))} 秒",
                    f"- 验证窗口：{tuning.get('validationSize', 0)}",
                    f"- 是否提前停止：{'是' if tuning.get('stoppedEarly') else '否'}",
                    f"- 最佳 MAE：{_format_metric(tuning.get('bestMetric'))}",
                    "",
                    "最终选中参数：",
                    "```json",
                    json.dumps(tuning.get("selectedParams", {}), ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

            trials = tuning.get("trials", [])
            if trials:
                lines.extend(
                    [
                        "| 轮次 | 状态 | 选中 | MAE | RMSE | WAPE | 耗时(秒) | 参数 | 备注 |",
                        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                    ]
                )
                for trial in trials:
                    metrics = trial.get("metrics") or {}
                    lines.append(
                        "| "
                        + " | ".join(
                            [
                                _md_cell(trial.get("round") or "—"),
                                _md_cell(trial.get("status") or "unknown"),
                                _md_cell("是" if trial.get("selected") else "否"),
                                _md_cell(_format_metric(metrics.get("mae") if isinstance(metrics, dict) else None)),
                                _md_cell(_format_metric(metrics.get("rmse") if isinstance(metrics, dict) else None)),
                                _md_cell(_format_metric(metrics.get("wape") if isinstance(metrics, dict) else None)),
                                _md_cell(_format_metric(trial.get("elapsedSeconds"))),
                                _md_cell(json.dumps(trial.get("params", {}), ensure_ascii=False, separators=(", ", ": "))),
                                _md_cell(trial.get("message") or ""),
                            ]
                        )
                        + " |"
                    )
                lines.append("")
            else:
                lines.extend(["未记录逐轮候选结果。", ""])

            warnings = tuning.get("warnings", []) if options.includeWarnings else []
            if warnings:
                lines.append("调参提示：")
                lines.extend([f"- {warning}" for warning in warnings])
                lines.append("")

    return "\n".join(lines).strip()


def generate_deepseek_report(api_key: str, base_url: str, model: str, context: dict[str, Any], options: ReportOptions) -> str:
    base_messages = build_report_prompt(context, options)
    chunks: list[str] = []
    last_finish_reason: str | None = None

    try:
        for _attempt in range(4):
            messages = base_messages
            if chunks:
                messages = [
                    *base_messages,
                    {"role": "assistant", "content": _combine_chunks(chunks)},
                    {
                        "role": "user",
                        "content": "你上一条 Markdown 报告被截断了。请从上文最后未完成的位置继续，禁止重复已经写过的内容，必须补齐剩余章节、附录和结束段落后自然收尾。",
                    },
                ]
            content, last_finish_reason = _request_completion(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=messages,
                max_tokens=_report_max_tokens(options.length),
            )
            chunks.append(content)
            if last_finish_reason != "length":
                break

        narrative = _combine_chunks(chunks)
        if not narrative:
            raise AppError("DeepSeek returned an empty report.", code="DEEPSEEK_EMPTY_REPORT")

        appendices = [
            appendix
            for appendix in [
                _build_feature_workflow_appendix(context, options),
                _build_recommendation_appendix(context, options),
                _build_visual_appendix(context, options),
                _build_tuning_appendix(context, options),
            ]
            if appendix.strip()
        ]
        if last_finish_reason == "length":
            narrative = (
                narrative.rstrip()
                + "\n\n> 注：上方 AI 叙述达到模型输出上限；完整的 feature pipeline、workflow、模型推荐与自动优化逐轮明细已在下方附录补齐。"
            )
        if not appendices:
            return narrative.strip()
        return f"{narrative.strip()}\n\n---\n\n" + "\n\n---\n\n".join(appendices)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(_sanitize_error(exc), code="DEEPSEEK_REPORT_FAILED") from exc
