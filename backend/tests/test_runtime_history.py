from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.models import ExperimentRecord
from app.services.runtime_history import load_runtime_from_record


def test_load_runtime_from_record_reconstructs_history_without_runtime_json():
    created_at = datetime(2026, 7, 2, 9, 15, 2, tzinfo=timezone.utc)
    record = ExperimentRecord(
        id="exp_history_runtime",
        name="history-runtime",
        file_name="electricity.csv",
        sheet_name="CSV",
        target_column="OT",
        recommended_model_id="lightgbm",
        best_mae="154.87",
        model_count="2",
        config_json=json.dumps(
            {
                "selectedModels": ["lightgbm", "timesfm"],
                "parameterStrategy": "auto",
            }
        ),
        data_profile_json=json.dumps(
            {
                "targets": [
                    {
                        "targetColumn": "OT",
                        "detectedFrequency": "H",
                        "sourceFrequency": "H",
                        "history": [{"time": "2026-01-01T00:00:00", "value": 1.0}],
                        "featureConfig": {
                            "lagFeatures": True,
                            "rollingFeatures": True,
                            "calendarFeatures": True,
                            "covariates": True,
                        },
                        "covariateColumns": ["holiday", "temp"],
                        "warnings": ["Detected 2 IQR outliers; values were not changed."],
                    }
                ]
            }
        ),
        metrics_json="[]",
        backtest_json="{}",
        diagnostics_json="{}",
        series_json="[]",
        final_forecast_json=None,
        model_logs_json=json.dumps(
            [
                {
                    "modelId": "lightgbm",
                    "modelName": "LightGBM",
                    "targetColumn": "OT",
                    "status": "success",
                    "metrics": {"mae": 154.87},
                    "warnings": ["uses_feature_importance"],
                    "runtime": {"fitSeconds": 6.4, "predictSeconds": 0.1},
                    "tuning": {
                        "enabled": True,
                        "strategy": "auto",
                        "tuningSeconds": 15.7,
                        "candidateCount": 2,
                        "candidateLimit": 10,
                        "bestMetric": 106.2,
                        "selectedParams": {"nEstimators": 120, "numLeaves": 15},
                        "trials": [
                            {
                                "round": 1,
                                "status": "success",
                                "elapsedSeconds": 7.5,
                                "message": "评估成功。",
                                "params": {"nEstimators": 80},
                                "metrics": {"mae": 112.3},
                            },
                            {
                                "round": 2,
                                "status": "success",
                                "elapsedSeconds": 8.2,
                                "message": "评估成功。",
                                "params": {"nEstimators": 120, "numLeaves": 15},
                                "metrics": {"mae": 106.2},
                                "selected": True,
                            },
                        ],
                    },
                    "explainability": {
                        "modelId": "lightgbm",
                        "modelName": "LightGBM",
                        "targetColumn": "OT",
                        "supported": True,
                        "warning": None,
                        "featureImportance": [
                            {"feature": "temp", "importance": 0.184, "rank": 1},
                            {"feature": "holiday", "importance": 0.091, "rank": 2},
                        ],
                        "shapSupported": True,
                        "shapWarning": None,
                        "shapTopFeatures": [
                            {"feature": "temp", "meanAbsShap": 9.2, "direction": "positive", "rank": 1},
                            {"feature": "holiday", "meanAbsShap": 4.1, "direction": "mixed", "rank": 2},
                        ],
                        "singlePoint": {
                            "time": "2026-01-02T00:00:00",
                            "actual": 150.0,
                            "predicted": 140.0,
                            "residual": 10.0,
                            "absoluteError": 10.0,
                            "contributions": [
                                {"feature": "temp", "value": 24.0, "shapValue": 5.2, "direction": "positive"},
                                {"feature": "holiday", "value": 1.0, "shapValue": -1.2, "direction": "negative"},
                            ],
                            "warnings": [],
                        },
                    },
                },
                {
                    "modelId": "timesfm",
                    "modelName": "TimesFM",
                    "targetColumn": "OT",
                    "status": "success",
                    "metrics": {"mae": 160.12},
                    "runtime": {"fitSeconds": 12.0, "predictSeconds": 0.5},
                    "tuning": {
                        "enabled": True,
                        "strategy": "auto",
                        "tuningSeconds": 1.1,
                        "candidateCount": 2,
                        "candidateLimit": 4,
                        "bestMetric": 160.12,
                        "selectedParams": {"contextWindow": 512, "normalization": "zscore"},
                        "trials": [
                            {
                                "round": 1,
                                "status": "success",
                                "elapsedSeconds": 0.5,
                                "message": "尝试短上下文。",
                                "params": {"contextWindow": 256},
                                "metrics": {"mae": 165.4},
                            },
                            {
                                "round": 2,
                                "status": "success",
                                "elapsedSeconds": 0.6,
                                "message": "切换归一化后表现更稳。",
                                "params": {"contextWindow": 512, "normalization": "zscore"},
                                "metrics": {"mae": 160.12},
                                "selected": True,
                            },
                        ],
                    },
                },
            ]
        ),
        runtime_json=None,
        manifest_json=json.dumps(
            {
                "data": {
                    "columns": ["ts", "OT", "holiday", "temp", "load", "region"]
                },
                "environment": {
                    "device": "mps",
                    "memoryTotalMb": 16384,
                    "memoryAvailableMb": 3620,
                }
            }
        ),
        config_hash=None,
        source_file_sha256=None,
        app_version="0.3.0",
        git_commit="test-commit",
        created_at=created_at,
    )

    runtime = load_runtime_from_record(record)

    assert runtime is not None
    assert runtime.runId == record.id
    assert runtime.status == "completed"
    assert runtime.currentStage == "finished"
    assert len(runtime.models) == 2
    assert len(runtime.featurePipeline) == 1
    assert len(runtime.optimization) == 2
    assert runtime.resources is not None
    assert runtime.resources.device == "mps"
    assert runtime.resources.gpuLabel == "Apple Silicon GPU"
    assert runtime.models[0].metricLabel == "MAE"
    assert runtime.models[0].currentMetric == 154.87
    assert runtime.models[0].bestMetric == 106.2
    assert runtime.models[0].selectedParams["nEstimators"] == 120
    assert runtime.models[0].warnings == ["uses_feature_importance"]
    assert runtime.featurePipeline[0].families[-1].id == "covariates"
    assert runtime.featurePipeline[0].families[-1].generatedCount == 2
    assert runtime.featurePipeline[0].summary is not None
    assert runtime.featurePipeline[0].summary.rawColumnCount == 6
    assert runtime.featurePipeline[0].summary.userCovariateCount == 2
    assert runtime.featurePipeline[0].summary.generatedFeatureCount >= 10
    assert runtime.featurePipeline[0].steps[1].label == "Data Profiling"
    assert runtime.featurePipeline[0].steps[3].label == "Feature Factory"
    assert runtime.featurePipeline[0].covariates[0].name == "holiday"
    assert runtime.featurePipeline[0].covariates[0].type == "known_future"
    assert runtime.featurePipeline[0].covariates[0].forecastStrategy == "calendar"
    assert runtime.featurePipeline[0].covariates[1].name == "temp"
    assert runtime.featurePipeline[0].covariates[1].type == "static"
    assert runtime.featurePipeline[0].machines[-1].id == "covariate_loader"
    assert "holiday" in runtime.featurePipeline[0].machines[-1].generatedFeatures
    assert "temp" in runtime.featurePipeline[0].machines[-1].generatedFeatures
    assert runtime.featurePipeline[0].selection.generatedCount >= runtime.featurePipeline[0].selection.selectedCount
    temp_node = next(node for node in runtime.featurePipeline[0].lineage if node.name == "temp")
    holiday_node = next(node for node in runtime.featurePipeline[0].lineage if node.name == "holiday")
    assert temp_node.importance == 0.184
    assert temp_node.shap == 9.2
    assert temp_node.important is True
    assert holiday_node.importance == 0.091
    assert holiday_node.shap == 4.1
    assert runtime.optimization[0].strategyLabel == "Optuna Optimization Engine"
    assert runtime.optimization[1].strategyLabel == "Foundation Model Context Search"
    assert runtime.optimization[1].trials[1].selected is True
