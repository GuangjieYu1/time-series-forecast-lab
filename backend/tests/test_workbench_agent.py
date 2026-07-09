from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_workbench_agent_routes_data_and_model_ideas():
    client = TestClient(app)
    known_future_response = client.post(
        "/api/workbench-agent/ideas/analyze",
        json={
            "idea": "我想把节假日因素加进去看看",
            "context": {"targetColumn": "passenger_count", "frequency": "D", "availableColumns": ["date", "passenger_count"], "horizon": 14, "domain": "aviation"},
            "mode": "offline",
        },
    )
    assert known_future_response.status_code == 200, known_future_response.text
    known_future = known_future_response.json()
    assert known_future["route"] == "feature_engineering_data"
    assert known_future["candidateDataSources"]
    assert known_future["covariatePlan"]["covariateType"] == "known_future"

    static_response = client.post(
        "/api/workbench-agent/ideas/analyze",
        json={
            "idea": "我想把航油价格加进去看看",
            "context": {"targetColumn": "passenger_count", "frequency": "D", "availableColumns": ["date", "passenger_count"], "horizon": 14, "domain": "aviation"},
            "mode": "offline",
        },
    )
    assert static_response.status_code == 200, static_response.text
    static_plan = static_response.json()
    assert static_plan["covariatePlan"]["covariateType"] == "static"
    assert static_plan["leakageWarnings"]

    model_response = client.post("/api/workbench-agent/ideas/analyze", json={"idea": "设计一个异常鲁棒的分段趋势模型", "context": {"targetColumn": "value"}, "mode": "offline"})
    assert model_response.status_code == 200, model_response.text
    model = model_response.json()
    assert model["route"] == "custom_model"
    assert model["customModelSpec"]["executableCodeAllowed"] is False


def test_workbench_agent_custom_model_validation_blocks_executable_specs():
    client = TestClient(app)
    response = client.post("/api/workbench-agent/custom-models/validate", json={"spec": {"objective": "run code", "predictionInterface": "fit/predict", "executableCodeAllowed": True}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is False
    assert body["normalizedSpec"]["executableCodeAllowed"] is False
