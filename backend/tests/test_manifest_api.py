from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_upload_preview_returns_sha256_and_manifest_endpoints(generated_fixtures: Path):
    client = TestClient(app)
    fixture = generated_fixtures / "daily_air_passengers.csv"

    with fixture.open("rb") as handle:
        upload_response = client.post("/api/upload/preview", files={"file": (fixture.name, handle, "text/csv")})
    assert upload_response.status_code == 200, upload_response.text
    upload_body = upload_response.json()
    assert upload_body["fileSha256"]

    request = {
        "runId": "run_manifest_daily",
        "uploadId": upload_body["uploadId"],
        "sheetName": "CSV",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["passenger_count"],
        "aggregation": {"enabled": False, "method": "sum"},
        "frequency": "auto",
        "horizon": 7,
        "testSize": 7,
        "selectedModels": ["naive", "moving_average"],
        "modelParameters": {"moving_average": {"window": 7}},
        "missingValueStrategy": "drop",
        "fillMissingTimeSteps": True,
        "duplicateTimeStrategy": "mean",
        "outlierStrategy": "none",
        "outlierIqrMultiplier": 1.5,
        "trimStrings": True,
        "runProfile": "balanced",
        "parameterStrategy": "default",
        "randomSeed": 42,
    }
    run_response = client.post("/api/forecast/run", json=request)
    assert run_response.status_code == 200, run_response.text
    experiment_id = run_response.json()["experimentId"]

    manifest_response = client.get(f"/api/experiments/{experiment_id}/manifest")
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["schemaVersion"] == "0.4"
    assert manifest["configHash"]
    assert manifest["sourceFileSha256"] == upload_body["fileSha256"]
    assert manifest["datasetHash"] == upload_body["fileSha256"]
    assert manifest["featurePipelineVersion"] == "0.4"
    assert manifest["runtimeEventSchemaVersion"] == "0.4"
    assert manifest["randomSeed"] == 42
    assert manifest["data"]["sheetName"] == "CSV"
    assert manifest["featurePipelines"]
    feature_pipeline = manifest["featurePipelines"][0]
    assert feature_pipeline["traceMode"] == "live"
    assert feature_pipeline["progressPercent"] == 100
    assert any(step["id"] == "leakage_guard" and step["status"] == "completed" for step in feature_pipeline["steps"])
    assert all("rows" not in (step.get("outputProfile") or {}) for step in feature_pipeline["steps"])

    events_response = client.get(f"/api/runtime/{experiment_id}/events")
    assert events_response.status_code == 200, events_response.text
    events = events_response.json()["events"]
    assert events
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["eventType"] == "terminal"

    rerun_response = client.post("/api/experiments/rerun", json={"experimentId": experiment_id})
    assert rerun_response.status_code == 200, rerun_response.text
    rerun_body = rerun_response.json()
    assert rerun_body["runRequestTemplate"]["sheetName"] == "CSV"
    assert rerun_body["fileMatch"]["warnings"]

    download_response = client.get(f"/api/experiments/{experiment_id}/manifest/download")
    assert download_response.status_code == 200
    assert "attachment" in download_response.headers.get("content-disposition", "").lower()

    client.delete(f"/api/experiments/{experiment_id}")
