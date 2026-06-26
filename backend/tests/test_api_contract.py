from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.storage import delete_upload, read_upload_metadata
from app.main import app


def test_error_contract_for_unsupported_upload():
    client = TestClient(app)
    response = client.post("/api/upload/preview", files={"file": ("bad.txt", b"date,value\n2026-01-01,1\n", "text/plain")})
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "code", "details"}
    assert "Unsupported file format" in body["message"]


def test_upload_preview_csv_and_multi_sheet_xlsx(generated_fixtures: Path):
    client = TestClient(app)
    csv_path = generated_fixtures / "daily_air_passengers.csv"
    with csv_path.open("rb") as handle:
        csv_response = client.post("/api/upload/preview", files={"file": (csv_path.name, handle, "text/csv")})
    assert csv_response.status_code == 200
    csv_body = csv_response.json()
    assert csv_body["sheets"][0]["previewRows"][0]["date"] == "2026-06-01"
    delete_upload(csv_body["uploadId"])

    xlsx_path = generated_fixtures / "raw_flight_detail_multi_sheet.xlsx"
    with xlsx_path.open("rb") as handle:
        xlsx_response = client.post(
            "/api/upload/preview",
            files={"file": (xlsx_path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert xlsx_response.status_code == 200
    xlsx_body = xlsx_response.json()
    sheet_names = {sheet["sheetName"] for sheet in xlsx_body["sheets"]}
    assert {"domestic", "international"}.issubset(sheet_names)
    delete_upload(xlsx_body["uploadId"])


def test_raw_multi_sheet_end_to_end_history_and_cleanup(generated_fixtures: Path):
    client = TestClient(app)
    fixture = generated_fixtures / "raw_flight_detail_multi_sheet.xlsx"
    with fixture.open("rb") as handle:
        upload_response = client.post(
            "/api/upload/preview",
            files={"file": (fixture.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert upload_response.status_code == 200
    upload_id = upload_response.json()["uploadId"]
    upload_path = Path(read_upload_metadata(upload_id)["path"])
    assert upload_path.exists()

    request = {
        "uploadId": upload_id,
        "sheetName": "domestic",
        "dataMode": "raw",
        "timeColumn": "flight_date",
        "targetColumns": ["passenger_count"],
        "aggregation": {"enabled": True, "method": "sum"},
        "frequency": "auto",
        "horizon": 7,
        "testSize": 7,
        "selectedModels": ["naive", "seasonal_naive", "moving_average", "arima", "ets", "prophet", "timesfm"],
        "missingValueStrategy": "drop",
        "fillMissingTimeSteps": True,
    }
    forecast_response = client.post("/api/forecast/run", json=request)
    assert forecast_response.status_code == 200, forecast_response.text
    forecast_body = forecast_response.json()
    assert forecast_body["recommendedModelId"]
    assert forecast_body["backtest"]["predictions"]
    assert not upload_path.exists()

    failed_models = [model for model in forecast_body["rankedModels"] if model["status"] == "failed"]
    assert all(model["error"] for model in failed_models)
    assert forecast_body["rankedModels"][0]["status"] == "success"

    experiment_id = forecast_body["experimentId"]
    final_response = client.post(
        "/api/forecast/final",
        json={"experimentId": experiment_id, "finalModelId": forecast_body["recommendedModelId"], "horizon": 7},
    )
    assert final_response.status_code == 200, final_response.text
    assert len(final_response.json()["forecast"]) == 7

    list_response = client.get("/api/experiments")
    assert list_response.status_code == 200
    assert any(item["experimentId"] == experiment_id for item in list_response.json())

    detail_response = client.get(f"/api/experiments/{experiment_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["backtest"]["predictions"]
    assert detail["finalForecast"]["forecast"]
    assert "flight_no" not in detail["series"][0]

    delete_response = client.delete(f"/api/experiments/{experiment_id}")
    assert delete_response.status_code == 200
    assert not any(item["experimentId"] == experiment_id for item in client.get("/api/experiments").json())
