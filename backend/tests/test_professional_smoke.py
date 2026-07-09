from __future__ import annotations

import importlib.util
from pathlib import Path

def test_etth1_xgboost_forecast_smoke(authed_client):
    client = authed_client.client
    fixture = Path(__file__).parent / "fixtures" / "professional" / "ETTh1.csv"

    with fixture.open("rb") as handle:
        upload_response = client.post("/api/upload/preview", files={"file": (fixture.name, handle, "text/csv")})
    assert upload_response.status_code == 200, upload_response.text
    upload_id = upload_response.json()["uploadId"]

    request = {
        "runId": "run_smoke_etth1_xgboost",
        "uploadId": upload_id,
        "sheetName": "CSV",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["OT"],
        "aggregation": {"enabled": False, "method": "sum"},
        "frequency": "auto",
        "horizon": 24,
        "testSize": 24,
        "selectedModels": ["naive", "xgboost"],
        "modelParameters": {"xgboost": {"nEstimators": 40, "maxDepth": 2, "learningRate": 0.08}},
        "missingValueStrategy": "drop",
        "fillMissingTimeSteps": True,
        "duplicateTimeStrategy": "mean",
        "outlierStrategy": "none",
        "outlierIqrMultiplier": 1.5,
        "trimStrings": True,
    }
    forecast_response = client.post("/api/forecast/run", json=request)
    assert forecast_response.status_code == 200, forecast_response.text
    body = forecast_response.json()
    client.delete(f"/api/experiments/{body['experimentId']}")

    assert body["detectedFrequency"] == "H"
    assert len(body["backtest"]["actual"]) == 24
    model_status = {model["modelId"]: model["status"] for model in body["rankedModels"]}
    assert model_status["naive"] == "success"
    assert model_status["xgboost"] in {"success", "failed"}
    if importlib.util.find_spec("xgboost") is not None:
        assert model_status["xgboost"] == "success"
        assert len(body["backtest"]["predictions"]["xgboost"]) == 24
