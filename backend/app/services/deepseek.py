from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.errors import AppError
from app.schemas import DeepSeekConnectionResponse, ReportOptions
from app.services.auto_tuning.service import describe_tuning_profile


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
        "rankedModels": ranked_models,
        "targets": targets,
        "autoTuning": _build_auto_tuning_summary(experiment, targets),
        "topResidualPoints": top_residuals[:12],
        "finalForecastSummary": _forecast_summary(final_forecast),
        "modelLogs": experiment.get("modelLogs", []),
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
    system = (
        "你是资深时间序列预测分析师。请基于给定实验摘要生成中文 Markdown 报告。"
        "不要声称看过原始文件或完整业务明细；只使用摘要、指标、残差、调参记录和预测结果。"
        "残差定义必须保持为 residual = actual - predicted。"
        "如果启用了自动优化，必须解释优化策略、候选参数变化与指标变化的关系，以及最终参数为何被选中。"
    )
    user = f"""
请生成一份{options.style}风格、{options.length}长度的中文时间序列预测分析报告。

报告必须包含：
1. 数据概览
2. 模型对比结论
3. 自动优化策略说明（如果本次开启了自动优化）
4. 参数变化与结果变化分析
5. 残差分析
6. 最终预测结果
7. 业务解释
8. 建议
9. 风险与限制

写作要求：
- 使用 Markdown，并优先使用二级、三级标题组织结构。
- 保留 MAE、MSE、RMSE、WAPE、Residual、Holdout 等术语，并给中文解释。
- 明确说明 residual = actual - predicted，正残差代表模型低估，负残差代表模型高估。
- 如果某些模型失败，要解释为单模型失败，不影响其他模型比较。
- 如果有自动调参记录，要分析候选参数如何影响 MAE / RMSE / WAPE，并解释最终选型逻辑。
- 可以使用 Markdown 表格总结关键候选，但不要把整段 JSON 原样重复到正文里。
- 不要输出 API Key、不要编造不存在的原始明细。

实验摘要如下：
```json
{compact_context}
```
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _report_max_tokens(length: str) -> int:
    if length == "long":
        return 3600
    if length == "medium":
        return 2400
    return 1400


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


def _build_tuning_appendix(context: dict[str, Any], options: ReportOptions) -> str:
    auto_tuning = context.get("autoTuning", {})
    targets = context.get("targets", [])
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
                    f"- 调参策略：`{tuning.get('strategy') or 'default'}` / `profile={tuning.get('profile') or 'balanced'}`",
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
        for _attempt in range(3):
            messages = base_messages
            if chunks:
                messages = [
                    *base_messages,
                    {"role": "assistant", "content": _combine_chunks(chunks)},
                    {
                        "role": "user",
                        "content": "你上一条 Markdown 报告被截断了。请从上文最后未完成的位置继续，禁止重复已经写过的内容，补齐剩余章节并自然结束。",
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

        appendix = _build_tuning_appendix(context, options)
        if last_finish_reason == "length":
            narrative = (
                narrative.rstrip()
                + "\n\n> 注：上方 AI 叙述达到模型输出上限；完整的自动优化逐轮明细和最终选型信息已在下方附录补齐。"
            )
        return f"{narrative.strip()}\n\n---\n\n{appendix.strip()}"
    except AppError:
        raise
    except Exception as exc:
        raise AppError(_sanitize_error(exc), code="DEEPSEEK_REPORT_FAILED") from exc
