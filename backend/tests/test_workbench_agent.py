from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_workbench_agent_routes_data_and_model_ideas():
    client = TestClient(app)
    data_response = client.post(
        "/api/workbench-agent/ideas/analyze",
        json={
            "idea": "我想把航油价格和节假日因素加进去看看",
            "context": {"targetColumn": "passenger_count", "frequency": "D", "availableColumns": ["date", "passenger_count"], "horizon": 14, "domain": "aviation"},
            "mode": "offline",
        },
    )
    assert data_response.status_code == 200, data_response.text
    data = data_response.json()
    assert data["route"] == "feature_engineering_data"
    assert data["candidateDataSources"]
    assert data["covariatePlan"]["covariateType"] in {"known_future", "unknown_future"}

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
