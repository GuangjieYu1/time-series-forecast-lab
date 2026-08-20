from app.services.agent import orchestrator as agent_orchestrator_module
from app.services.agent.orchestrator import SkillExecutionResult
from app.schemas import AgentContextSnapshot, AgentLlmConfig, AgentPlanStep, AgentRunRequest


def test_parse_llm_json_accepts_markdown_wrapped_object():
    payload = """
```json
{
  "goal": "分析 HUFL 主因",
  "skillIds": ["read_explainability", "read_residual_diagnostics"]
}
```
""".strip()

    parsed = agent_orchestrator_module._parse_llm_json(payload)

    assert parsed["goal"] == "分析 HUFL 主因"
    assert parsed["skillIds"] == ["read_explainability", "read_residual_diagnostics"]


def test_parse_llm_json_repairs_pythonish_object():
    payload = "{'goal': '分析 HUFL 主因', 'skillIds': ['read_explainability'],}"

    parsed = agent_orchestrator_module._parse_llm_json(payload)

    assert parsed["goal"] == "分析 HUFL 主因"
    assert parsed["skillIds"] == ["read_explainability"]


def test_plan_skill_ids_with_llm_falls_back_to_heuristic_order(monkeypatch):
    monkeypatch.setattr(agent_orchestrator_module, "_planning_evidence", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        agent_orchestrator_module,
        "request_deepseek_text",
        lambda **kwargs: "我会优先看 explainability、residual diagnostics 和 covariate flow。",
    )

    request = AgentRunRequest(
        prompt="影响HUFL列的主要原因是什么？",
        llm=AgentLlmConfig(
            provider="deepseek",
            apiKey="test-key",
            baseUrl="https://api.deepseek.com",
            model="deepseek-v4-flash",
            stream=True,
        ),
    )
    context = AgentContextSnapshot(
        experimentId="exp_demo",
        experimentName="HUFL Attribution Analysis",
        workspaceId="ws_demo",
        targetColumn="HUFL",
        recommendedModelId="attribution_evidence",
        currentPage="/experiments/:id/attribution",
        currentTab="attribution",
    )
    skill_ids = agent_orchestrator_module._plan_skill_ids_with_llm(
        request=request,
        context=context,
        bundle={"attribution": {"overview": {"summary": []}, "quickDiagnosis": {"summary": []}}},
    )

    assert skill_ids == agent_orchestrator_module._select_skill_ids(request.prompt, target_column="HUFL")


def test_build_pre_evidence_plan_message_only_contains_plan_and_action():
    message = agent_orchestrator_module._build_pre_evidence_plan_message(
        prompt="影响HUFL列的主要原因是什么？",
        target_column="HUFL",
        plan_outline="1. Read Explainability",
        plan=[
            AgentPlanStep(
                stepId="step_1",
                title="Read Explainability",
                skillId="read_explainability",
                status="pending",
                description="读取 Feature Importance、SHAP 和推荐单点解释。",
            ),
            AgentPlanStep(
                stepId="step_2",
                title="Read Residual Diagnostics",
                skillId="read_residual_diagnostics",
                status="pending",
                description="读取 residual 诊断与最大异常点。",
            ),
        ],
    )

    assert "影响HUFL列的主要原因是什么？" in message
    assert "发现" in message
    assert "解释" in message
    assert "下一步" in message
    assert "当前先聚焦" in message
    assert "证据路线排清楚" in message
    assert "Read Explainability" in message
    assert "Read Residual Diagnostics" in message
    assert "真实结果" in message


def test_build_step_transcript_message_is_clean_and_structured():
    message = agent_orchestrator_module._build_step_transcript_message(
        step=AgentPlanStep(
            stepId="step_1",
            title="Read Explainability",
            skillId="read_explainability",
            status="completed",
            description="读取 Feature Importance、SHAP 和推荐单点解释。",
        ),
        result=SkillExecutionResult(
            output_summary="已读取树模型驱动解释。",
            warnings=["当前只有 1 个可解释特征。"],
        ),
        next_step_title="Read Residual Diagnostics",
    )

    assert "发现" in message
    assert "解释" in message
    assert "下一步" in message
    assert "Read Residual Diagnostics" in message
    assert "根据输入生成步骤摘要" not in message
