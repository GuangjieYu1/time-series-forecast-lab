from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete

from app.db.models import ExperimentRecord
from app.db.session import SessionLocal


def test_experiment_explainability_api_reads_persisted_artifacts(authed_client):
    experiment_id = "exp_explainability_api"
    db = SessionLocal()
    try:
        db.execute(delete(ExperimentRecord).where(ExperimentRecord.id == experiment_id))
        db.add(
            ExperimentRecord(
                id=experiment_id,
                workspace_id=authed_client.workspace_id,
                created_by_user_id=authed_client.user_id,
                name="Explainability API",
                file_name="demo.csv",
                sheet_name="CSV",
                target_column="value",
                recommended_model_id="lightgbm",
                best_mae="12.3",
                model_count="2",
                config_json="{}",
                data_profile_json=json.dumps({"targets": []}),
                metrics_json="[]",
                backtest_json=json.dumps({"actual": [], "predictions": {}}),
                diagnostics_json=json.dumps({"warnings": []}),
                series_json="[]",
                final_forecast_json=None,
                model_logs_json=json.dumps(
                    [
                        {
                            "modelId": "lightgbm",
                            "modelName": "LightGBM",
                            "targetColumn": "value",
                            "explainability": {
                                "modelId": "lightgbm",
                                "modelName": "LightGBM",
                                "targetColumn": "value",
                                "supported": True,
                                "warning": None,
                                "featureImportance": [{"feature": "lag_7", "importance": 0.184, "rank": 1}],
                                "shapSupported": False,
                                "shapWarning": "SHAP disabled because package is unavailable",
                                "shapTopFeatures": [],
                                "singlePoint": {
                                    "time": "2026-01-10T00:00:00",
                                    "actual": 90.0,
                                    "predicted": 82.0,
                                    "residual": 8.0,
                                    "absoluteError": 8.0,
                                    "contributions": [{"feature": "lag_7", "value": 80.0, "shapValue": 4.2, "direction": "positive"}],
                                    "warnings": [],
                                },
                            },
                        },
                        {
                            "modelId": "arima",
                            "modelName": "ARIMA",
                            "targetColumn": "value",
                        },
                    ]
                ),
                runtime_json=None,
                manifest_json=json.dumps({"schemaVersion": "0.4"}),
                config_hash="hash",
                source_file_sha256="sha",
                app_version="test",
                git_commit=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        response = authed_client.client.get(f"/api/experiments/{experiment_id}/explainability")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["experimentId"] == experiment_id
        assert body["recommendedModelId"] == "lightgbm"
        assert [item["modelId"] for item in body["models"]] == ["lightgbm", "arima"]
        assert body["models"][0]["featureImportance"][0]["feature"] == "lag_7"
        assert body["models"][0]["shapWarning"] == "SHAP disabled because package is unavailable"
        assert body["models"][0]["singlePoint"]["absoluteError"] == 8.0
        assert body["models"][1]["supported"] is False
        assert body["models"][1]["warning"] == "当前模型暂不支持 SHAP"
    finally:
        db.execute(delete(ExperimentRecord).where(ExperimentRecord.id == experiment_id))
        db.commit()
        db.close()
