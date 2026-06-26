from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.errors import AppError
from app.schemas import DeepSeekConnectionResponse, ReportOptions


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
        "topResidualPoints": top_residuals[:12],
        "finalForecastSummary": _forecast_summary(final_forecast),
        "modelLogs": experiment.get("modelLogs", []),
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
        "不要声称看过原始文件或完整业务明细；只使用摘要、指标、残差和预测结果。"
        "残差定义必须保持为 residual = actual - predicted。"
    )
    user = f"""
请生成一份{options.style}风格、{options.length}长度的中文时间序列预测分析报告。

报告必须包含：
1. 数据概览
2. 模型对比结论
3. 残差分析
4. 最终预测结果
5. 业务解释
6. 建议
7. 风险与限制

写作要求：
- 使用 Markdown。
- 保留 MAE、MSE、RMSE、WAPE、Residual、Holdout 等术语，并给中文解释。
- 明确说明 residual = actual - predicted，正残差代表模型低估，负残差代表模型高估。
- 如果某些模型失败，要解释为单模型失败，不影响其他模型比较。
- 不要输出 API Key、不要编造不存在的原始明细。

实验摘要如下：
```json
{compact_context}
```
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_deepseek_report(api_key: str, base_url: str, model: str, context: dict[str, Any], options: ReportOptions) -> str:
    payload = {
        "model": model,
        "messages": build_report_prompt(context, options),
        "temperature": 0.2,
        "max_tokens": 2200 if options.length == "long" else 1400 if options.length == "medium" else 800,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(_endpoint(base_url), headers=_headers(api_key), json=payload)
            response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise AppError("DeepSeek returned an empty report.", code="DEEPSEEK_EMPTY_REPORT")
        return content.strip()
    except AppError:
        raise
    except Exception as exc:
        raise AppError(_sanitize_error(exc), code="DEEPSEEK_REPORT_FAILED") from exc
