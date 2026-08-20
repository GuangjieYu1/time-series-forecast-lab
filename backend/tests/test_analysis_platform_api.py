from __future__ import annotations

from io import BytesIO

from app.core.storage import delete_upload


def _upload_csv(authed_client, name: str, content: str) -> str:
    response = authed_client.client.post(
        "/api/upload/preview",
        files={"file": (name, BytesIO(content.encode("utf-8")), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()["uploadId"]


def _analysis_fixture_csv() -> str:
    rows = ["date,target,feature_a,feature_b,segment,order_id,constant_flag"]
    for index in range(1, 31):
        rows.append(
            ",".join(
                [
                    f"2026-06-{index:02d}",
                    str(120 + index * 3),
                    str(30 + index),
                    str(70 + (index % 5) * 4),
                    "domestic" if index % 2 else "international",
                    f"OID{1000 + index}",
                    "1",
                ]
            )
        )
    return "\n".join(rows) + "\n"


def test_analysis_profile_and_route_suggestion(authed_client):
    upload_id = _upload_csv(authed_client, "analysis_platform.csv", _analysis_fixture_csv())
    try:
        profile_response = authed_client.client.post(
            "/api/analysis/profile",
            json={"uploadId": upload_id, "sheetName": "CSV"},
        )
        assert profile_response.status_code == 200, profile_response.text
        profile = profile_response.json()
        assert profile["timeColumnCandidates"][0] == "date"
        assert "target" in profile["targetCandidates"]
        assert any(issue["issueType"] == "constant_column" for issue in profile["issues"])
        assert any(issue["issueType"] == "suspected_identifier" for issue in profile["issues"])
        assert profile["readinessScore"]["overall"] > 0

        route_response = authed_client.client.post(
            "/api/analysis/routes/suggest",
            json={"uploadId": upload_id, "sheetName": "CSV"},
        )
        assert route_response.status_code == 200, route_response.text
        routes = route_response.json()
        recommended_types = {item["analysisType"] for item in routes["recommendedRoutes"]}
        assert {"forecast", "attribution", "supervised_ml", "clustering"}.issubset(recommended_types)
    finally:
        delete_upload(upload_id)


def test_analysis_transform_plan_and_execute_create_new_upload_snapshot(authed_client):
    upload_id = _upload_csv(authed_client, "analysis_transform.csv", _analysis_fixture_csv())
    generated_upload_id: str | None = None
    try:
        plan_response = authed_client.client.post(
            "/api/analysis/transforms/plan",
            json={
                "uploadId": upload_id,
                "sheetName": "CSV",
                "transformType": "drop_constant_columns",
                "columns": ["constant_flag"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        assert plan["columns"] == ["constant_flag"]
        assert plan["willCreateNewDataset"] is True

        execute_response = authed_client.client.post(
            "/api/analysis/transforms/execute",
            json={
                "uploadId": upload_id,
                "sheetName": "CSV",
                "transformType": "drop_constant_columns",
                "columns": ["constant_flag"],
                "confirmed": True,
            },
        )
        assert execute_response.status_code == 200, execute_response.text
        payload = execute_response.json()
        generated_upload_id = payload["upload"]["uploadId"]
        assert generated_upload_id != upload_id
        assert "constant_flag" not in {column["name"] for column in payload["sheet"]["columns"]}
        assert payload["readinessAfter"]["overall"] >= payload["readinessBefore"]["overall"]
        assert "Readiness Score" in payload["qualityDeltaSummary"]
    finally:
        delete_upload(upload_id)
        if generated_upload_id:
            delete_upload(generated_upload_id)


def test_analysis_agent_returns_explanation_cards(authed_client):
    upload_id = _upload_csv(authed_client, "analysis_agent.csv", _analysis_fixture_csv())
    try:
        response = authed_client.client.post(
            "/api/analysis/agent/analyze",
            json={
                "uploadId": upload_id,
                "sheetName": "CSV",
                "prompt": "先帮我看看常量列和监督学习路线",
                "currentPage": "/analysis",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["plan"]
        assert payload["decisionCards"]
        assert any(card["actionType"] == "transform" for card in payload["decisionCards"])
        assert any(card["actionType"] == "workflow" for card in payload["decisionCards"])
        assert all("whatDetected" in card for card in payload["decisionCards"])
        assert all("whyRecommended" in card for card in payload["decisionCards"])
        assert all("ifSkipped" in card for card in payload["decisionCards"])
        assert all("expectedChange" in card for card in payload["decisionCards"])
    finally:
        delete_upload(upload_id)


def test_analysis_workflows_create_generic_experiments(authed_client):
    upload_id = _upload_csv(authed_client, "analysis_workflows.csv", _analysis_fixture_csv())
    try:
        base_request = {
            "uploadId": upload_id,
            "sheetName": "CSV",
            "targetColumn": "target",
            "timeColumn": "date",
            "groupingColumns": ["segment"],
            "featureColumns": ["feature_a", "feature_b", "segment"],
        }

        attribution_response = authed_client.client.post("/api/analysis/workflows/attribution/start", json=base_request)
        assert attribution_response.status_code == 200, attribution_response.text
        attribution = attribution_response.json()
        assert attribution["analysisType"] == "attribution"
        assert attribution["experimentId"]

        supervised_response = authed_client.client.post("/api/analysis/workflows/supervised-ml/start", json=base_request)
        assert supervised_response.status_code == 200, supervised_response.text
        supervised = supervised_response.json()
        assert supervised["analysisType"] == "supervised_ml"
        assert supervised["experimentId"]
        assert supervised["status"] == "running"
        assert supervised["stages"]
        assert supervised["configSummary"]["targetColumn"] == "target"

        clustering_response = authed_client.client.post(
            "/api/analysis/workflows/clustering/start",
            json={**base_request, "featureColumns": ["target", "feature_a", "feature_b"], "clusterCount": 3},
        )
        assert clustering_response.status_code == 200, clustering_response.text
        clustering = clustering_response.json()
        assert clustering["analysisType"] == "clustering"
        assert clustering["experimentId"]

        run_detail_response = authed_client.client.get(f"/api/analysis/runs/{supervised['runId']}")
        assert run_detail_response.status_code == 200, run_detail_response.text
        run_detail = run_detail_response.json()
        assert run_detail["analysisType"] == "supervised_ml"
        assert run_detail["stages"]
        assert run_detail["progressPercent"] >= 0

        run_events_response = authed_client.client.get(f"/api/analysis/runs/{supervised['runId']}/events")
        assert run_events_response.status_code == 200, run_events_response.text
        assert "events" in run_events_response.json()

        detail_response = authed_client.client.get(f"/api/experiments/{supervised['experimentId']}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["analysisType"] == "supervised_ml"
        assert detail["datasetProfile"]["uploadId"] == upload_id
        assert detail["analysisArtifacts"]
        assert detail["workflowState"]["stage"] == "completed"
    finally:
        delete_upload(upload_id)
