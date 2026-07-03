from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_runtime_estimate_endpoint_returns_model_estimates():
    client = TestClient(app)

    response = client.post(
        "/api/runtime/estimate",
        json={
            "rowCount": 26304,
            "frequency": "H",
            "totalColumnCount": 322,
            "targetCount": 1,
            "covariateCount": 320,
            "featureConfig": {
                "lagFeatures": True,
                "rollingFeatures": True,
                "calendarFeatures": True,
                "covariates": True,
            },
            "runProfile": "accurate",
            "parameterStrategy": "auto",
            "device": "cpu",
            "selectedModels": ["naive", "lightgbm", "random_forest", "timesfm"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["models"]) == 4
    estimates = {item["id"]: item for item in body["models"]}
    assert estimates["naive"]["estimatedSeconds"] > 0
    assert estimates["lightgbm"]["estimatedSeconds"] > estimates["naive"]["estimatedSeconds"]
    assert estimates["random_forest"]["estimatedSeconds"] > estimates["lightgbm"]["estimatedSeconds"]
    assert "timestamps" in estimates["timesfm"]["reason"]
    assert estimates["timesfm"]["computeTarget"] in {"cpu", "gpu"}


def test_runtime_estimate_rejects_unknown_models():
    client = TestClient(app)
    response = client.post(
        "/api/runtime/estimate",
        json={
            "rowCount": 1000,
            "frequency": "D",
            "totalColumnCount": 4,
            "targetCount": 1,
            "covariateCount": 0,
            "featureConfig": {
                "lagFeatures": True,
                "rollingFeatures": True,
                "calendarFeatures": True,
                "covariates": True,
            },
            "runProfile": "balanced",
            "parameterStrategy": "default",
            "device": "cpu",
            "selectedModels": ["not_real_model"],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "UNKNOWN_MODEL"
