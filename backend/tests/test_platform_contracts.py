from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ExperimentManifest, ModelProgress, RuntimeEvent
from app.services.runtime_tracker import RuntimeTracker, runtime_tracker
from benchmarks.schemas import BenchmarkSummary


def test_v03_manifest_remains_readable():
    manifest = ExperimentManifest.model_validate(
        {
            "schemaVersion": "0.3",
            "experimentId": "exp_legacy",
            "experimentName": "Legacy",
            "configHash": "config",
            "sourceFileSha256": "dataset",
            "environment": {
                "appVersion": "0.3.0",
                "pythonVersion": "3.12",
                "platform": "test",
                "device": "cpu",
            },
            "data": {
                "fileName": "legacy.csv",
                "fileSize": 10,
                "fileSha256": "dataset",
                "sheetName": "CSV",
                "columns": ["date", "value"],
                "timeColumn": "date",
                "targetColumns": ["value"],
            },
            "configuration": {},
        }
    )
    assert manifest.schemaVersion == "0.3"
    assert manifest.datasetHash is None
    assert manifest.featurePipelines == []


def test_runtime_event_contract_is_versioned():
    event = RuntimeEvent(
        id="evt_1",
        sequence=1,
        runId="run_1",
        timestamp=datetime.now(timezone.utc),
        eventType="model",
        stage="training",
        status="running",
        message="Training trial 1",
        modelId="xgboost",
        progressPercent=40,
    )
    assert event.schemaVersion == "0.4"


def test_benchmark_summary_contract_has_stable_shape():
    summary = BenchmarkSummary.model_validate(
        {
            "profile": "fast",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "seconds": 1.0,
            "totalCases": 0,
            "successfulRuns": 0,
            "failedRuns": 0,
            "successRate": 0.0,
            "failureRate": 0.0,
            "cases": [],
        }
    )
    assert summary.schemaVersion == "0.4"
    assert summary.successRate == 0.0

def test_runtime_tracker_emits_ordered_canonical_events():
    tracker = RuntimeTracker()
    tracker.start(
        "run_events",
        kind="backtest",
        model_rows=[ModelProgress(modelId="naive", modelName="Naive", targetColumn="value")],
        message="Starting",
    )
    tracker.set_overall(
        "run_events",
        stage="training",
        message="Training",
        overall_percent=50,
        current_target="value",
    )
    tracker.update_model(
        "run_events",
        target_column="value",
        model_id="naive",
        status="success",
        message="Finished model",
        progress_percent=100,
        current_stage="finished",
    )
    detail = tracker.finalize("run_events", status="completed", message="Finished")

    assert detail is not None
    assert [event.sequence for event in detail.events] == list(range(1, len(detail.events) + 1))
    assert detail.events[0].eventType == "stage"
    assert any(event.eventType == "model" for event in detail.events)
    assert detail.events[-1].eventType == "terminal"

def test_runtime_event_sse_supports_replay_after_sequence():
    run_id = "run_sse_feature_contract"
    runtime_tracker.start(
        run_id,
        kind="backtest",
        model_rows=[ModelProgress(modelId="naive", modelName="Naive", targetColumn="value")],
        message="Starting",
    )
    runtime_tracker.set_overall(
        run_id,
        stage="feature_engineering",
        message="Building features",
        overall_percent=20,
        current_target="value",
    )
    runtime_tracker.finalize(run_id, status="completed", message="Finished")

    response = TestClient(app).get(f"/api/runtime/{run_id}/events/stream?afterSequence=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: runtime" in response.text
    assert "id: 1\n" not in response.text
    assert '"eventType":"terminal"' in response.text
