from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.schema_compat import ensure_schema_compatibility
from app.schemas import ForecastRunRequest
from app.services.reproducibility import build_config_hash_payload, compute_config_hash
from sqlalchemy import create_engine, inspect


def _request(**overrides) -> ForecastRunRequest:
    payload = {
        "uploadId": "tmp_1",
        "sheetName": "CSV",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["value"],
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
    payload.update(overrides)
    return ForecastRunRequest.model_validate(payload)


def test_config_hash_is_stable_and_excludes_runtime_only_fields():
    base = _request()
    variant = _request(uploadId="tmp_2", runId="run_2", experimentName="new name")

    assert compute_config_hash(base) == compute_config_hash(variant)
    payload = build_config_hash_payload(base)
    assert "uploadId" not in payload


def test_config_hash_changes_when_cleaning_or_model_selection_changes():
    base = _request()
    changed_cleaning = _request(missingValueStrategy="ffill")
    changed_models = _request(selectedModels=["naive", "arima"])

    assert compute_config_hash(base) != compute_config_hash(changed_cleaning)
    assert compute_config_hash(base) != compute_config_hash(changed_models)


def test_config_hash_includes_covariates_and_feature_config():
    base = _request(
        covariateColumns=["temperature"],
        featureConfig={"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "covariates": True},
    )
    changed_covariates = _request(
        covariateColumns=["promo_flag"],
        featureConfig={"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "covariates": True},
    )
    changed_features = _request(
        covariateColumns=["temperature"],
        featureConfig={"lagFeatures": True, "rollingFeatures": False, "calendarFeatures": True, "covariates": True},
    )

    payload = build_config_hash_payload(base)
    assert payload["covariateColumns"] == ["temperature"]
    assert payload["featureConfig"]["rollingFeatures"] is True
    assert compute_config_hash(base) != compute_config_hash(changed_covariates)
    assert compute_config_hash(base) != compute_config_hash(changed_features)


def test_schema_compatibility_adds_v03_columns(tmp_path: Path):
    database_path = tmp_path / "compat.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE experiments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            file_name TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            target_column TEXT NOT NULL,
            recommended_model_id TEXT,
            best_mae TEXT,
            model_count TEXT,
            config_json TEXT NOT NULL,
            data_profile_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            backtest_json TEXT NOT NULL,
            diagnostics_json TEXT NOT NULL,
            series_json TEXT NOT NULL,
            final_forecast_json TEXT,
            model_logs_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    engine = create_engine(f"sqlite:///{database_path}")
    ensure_schema_compatibility(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("experiments")}

    assert {"manifest_json", "config_hash", "source_file_sha256", "app_version", "git_commit"}.issubset(columns)
