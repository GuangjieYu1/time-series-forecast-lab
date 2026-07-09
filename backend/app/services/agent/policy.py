from __future__ import annotations

from app.schemas import AgentContextSnapshot, AgentRunRequest


GUARDRAILS = [
    "不跨 workspace 读取数据。",
    "不读取未授权实验。",
    "不绕过 covariate leakage guardrail。",
    "不执行任意用户代码。",
    "不访问外部未知来源数据。",
    "不删除实验，也不覆盖历史结果。",
]


def plan_risks(request: AgentRunRequest, context: AgentContextSnapshot, *, will_run_models: bool = False) -> list[str]:
    risks = list(GUARDRAILS)
    prompt = request.prompt.lower()
    if "泄漏" in request.prompt or "future leakage" in prompt or any(item.leakageRisk for item in context.covariates):
        risks.append("当前问题涉及协变量泄漏，Agent 会优先展示策略警示而不是直接放宽限制。")
    if will_run_models:
        risks.append("当前计划包含重跑类动作；只有在源上下文足够时才会执行，否则降级为建议卡片。")
    if context.currentPage == "/forecast":
        risks.append("当前页面处于实验工作流中，Agent 只使用这个实验的上下文，不会扩散到其他工作区数据。")
    return risks
