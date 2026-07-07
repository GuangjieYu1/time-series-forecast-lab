from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.constants import BENCHMARK_RESULT_SCHEMA_VERSION
from app.main import app
from benchmarks.schemas import BenchmarkSummary
from benchmarks.benchmark_cases import build_cases
from benchmarks.benchmark_metrics import elapsed_seconds, max_rss_mb, now
from benchmarks.benchmark_report import write_summary
from benchmarks.generators.generate_fixtures import ensure_benchmark_fixtures

SUITE_ALIASES = {
    "all": {"stability", "aggregation_correctness", "feature_lift", "reproducibility", "agent_routing"},
    "stability": {"stability"},
    "aggregation": {"aggregation_correctness"},
    "aggregation-correctness": {"aggregation_correctness"},
    "aggregation_correctness": {"aggregation_correctness"},
    "feature-lift": {"feature_lift"},
    "feature_lift": {"feature_lift"},
    "reproducibility": {"reproducibility"},
    "agent": {"agent_routing"},
    "agent-routing": {"agent_routing"},
    "agent_routing": {"agent_routing"},
}

AGENT_GOLDEN = [
    {"name": "holiday_data", "idea": "把节假日和春节前后窗口加进去看看", "expectedRoute": "feature_engineering_data", "needsLeakageWarning": False},
    {"name": "weather_data", "idea": "加入天气和气温作为影响客流的外部变量", "expectedRoute": "feature_engineering_data", "needsLeakageWarning": True},
    {"name": "fuel_market", "idea": "把航油价格和股票指数行情参入模型", "expectedRoute": "feature_engineering_data", "needsLeakageWarning": True},
    {"name": "promo_data", "idea": "促销计划和排班计划应该作为未来已知协变量", "expectedRoute": "feature_engineering_data", "needsLeakageWarning": False},
    {"name": "custom_loss", "idea": "我想设计一个对低估惩罚更重的自定义损失函数", "expectedRoute": "custom_model", "needsLeakageWarning": False},
    {"name": "hierarchical_model", "idea": "做一个分层模型，机场和航线共享趋势但保留局部差异", "expectedRoute": "custom_model", "needsLeakageWarning": False},
    {"name": "robust_model", "idea": "构想一种异常鲁棒模型，节假日尖峰不要拖坏趋势", "expectedRoute": "custom_model", "needsLeakageWarning": False},
    {"name": "hybrid_market_model", "idea": "加入油价指数，同时做一个分段趋势模型", "expectedRoute": "hybrid", "needsLeakageWarning": True},
    {"name": "clarify_vague", "idea": "帮我把预测变得更准一点", "expectedRoute": "clarify", "needsLeakageWarning": False},
    {"name": "unsupported_sensitive", "idea": "读取未授权客户隐私和内幕数据来预测", "expectedRoute": "unsupported", "needsLeakageWarning": False},
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run transparent forecast lab benchmarks.")
    parser.add_argument("--profile", choices=["fast", "balanced", "accurate"], default="balanced")
    parser.add_argument("--suite", choices=sorted(SUITE_ALIASES), default="all")
    parser.add_argument("--agent-mode", choices=["offline", "online", "dual"], default="offline")
    parser.add_argument("--dirty-only", action="store_true")
    parser.add_argument("--large-only", action="store_true")
    parser.add_argument("--case")
    return parser.parse_args()


def _selected_cases(root: Path, args: argparse.Namespace):
    suites = SUITE_ALIASES[args.suite]
    cases = [case for case in build_cases(root) if case.suite in suites]
    if args.case:
        cases = [case for case in cases if case.name == args.case]
    if args.dirty_only:
        cases = [case for case in cases if case.category == "dirty"]
    if args.large_only:
        cases = [case for case in cases if case.category == "large"]
    return cases


def _assert(name: str, ok: bool, message: str, expected: Any = None, actual: Any = None, tolerance: float | None = None, status_if_false: str = "failed") -> dict:
    return {"name": name, "status": "passed" if ok else status_if_false, "message": message, "expected": expected, "actual": actual, "tolerance": tolerance}


def _passed(assertions: list[dict], run_status: str = "200") -> bool:
    return run_status in {"200", "skipped"} and all(item.get("status") != "failed" for item in assertions)


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _case_result_base(case, seconds: float, memory_mb: float) -> dict:
    return {
        "name": case.name,
        "suite": case.suite,
        "category": case.category,
        "fileFormat": case.path.suffix.lstrip(".") or "-",
        "targetColumns": case.request.get("targetColumns", []),
        "covariateColumns": case.request.get("covariateColumns", []),
        "selectedModels": case.request.get("selectedModels", []),
        "uploadStatus": "skipped",
        "runStatus": "skipped",
        "seconds": round(seconds, 4),
        "memoryMb": max(0.0, round(memory_mb, 2)),
        "warningCount": 0,
        "modelStatuses": {},
        "modelResults": [],
        "thresholds": dict(case.thresholds),
        "artifacts": {},
        "assertions": [],
        "passed": True,
    }


def _run_forecast_case(client: TestClient, case, profile: str, *, delete: bool = True) -> dict:
    case_started = now()
    memory_before = max_rss_mb()
    result = _case_result_base(case, 0.0, 0.0)
    error: str | None = None
    experiment_id: str | None = None
    try:
        with case.path.open("rb") as handle:
            upload_response = client.post("/api/upload/preview", files={"file": (case.path.name, handle, case.content_type)})
        result["uploadStatus"] = str(upload_response.status_code)
        if upload_response.status_code != 200:
            error = upload_response.text
            raise RuntimeError(error)
        upload_body = upload_response.json()
        selected_sheet = next((sheet for sheet in upload_body.get("sheets", []) if sheet.get("sheetName") == case.request["sheetName"]), None)
        selected_sheet = selected_sheet or (upload_body.get("sheets", []) or [None])[0]
        if isinstance(selected_sheet, dict):
            result["rowCount"] = selected_sheet.get("rowCountApprox")
            result["columnCount"] = len(selected_sheet.get("columns", []))
        run_request = {"runId": f"bench_{case.name}_{datetime.now(timezone.utc).timestamp()}", "uploadId": upload_body["uploadId"], "runProfile": profile, "parameterStrategy": "auto" if profile != "fast" else "default", "randomSeed": 42, **case.request}
        run_response = client.post("/api/forecast/run", json=run_request)
        result["runStatus"] = str(run_response.status_code)
        if run_response.status_code != 200:
            error = run_response.text
            raise RuntimeError(error)
        body = run_response.json()
        experiment_id = body["experimentId"]
        result["experimentId"] = experiment_id
        result["warningCount"] = len(body["diagnostics"].get("warnings", [])) + sum(len(model.get("warnings", [])) for model in body.get("rankedModels", []))
        result["bestMae"] = next((model["metrics"]["mae"] for model in body.get("rankedModels", []) if model.get("status") == "success" and isinstance(model.get("metrics"), dict) and model["metrics"].get("mae") is not None), None)
        result["dataHealthScore"] = (body.get("dataHealth") or {}).get("score")
        result["modelStatuses"] = {model["modelId"]: model["status"] for model in body.get("rankedModels", [])}
        result["modelResults"] = [{"modelId": model.get("modelId"), "modelName": model.get("modelName"), "status": model.get("status"), "warnings": model.get("warnings", []), "error": model.get("error"), "metrics": model.get("metrics")} for model in body.get("rankedModels", [])]
        result["artifacts"]["response"] = body
        detail_response = client.get(f"/api/experiments/{experiment_id}")
        if detail_response.status_code == 200:
            result["artifacts"]["detail"] = detail_response.json()
        if delete and experiment_id:
            client.delete(f"/api/experiments/{experiment_id}")
    except Exception as exc:
        if error is None:
            error = str(exc)
        result["error"] = error
    result["seconds"] = elapsed_seconds(case_started)
    result["memoryMb"] = max(0.0, round(max_rss_mb() - memory_before, 2))
    result["passed"] = result.get("runStatus") == "200" if not result["assertions"] else _passed(result["assertions"], result.get("runStatus", "failed"))
    return result


def _run_aggregation_case(client: TestClient, case, profile: str) -> dict:
    result = _run_forecast_case(client, case, profile)
    expected = case.expected.get("series", [])
    actual_history = (((result.get("artifacts") or {}).get("detail") or {}).get("series") or [])
    actual = [[item.get("time"), float(item.get("value"))] for item in actual_history]
    tolerance = float(case.thresholds.get("tolerance", 0.0))
    diffs = [abs(float(expected_item[1]) - float(actual_item[1])) for expected_item, actual_item in zip(expected, actual)]
    max_diff = max(diffs) if diffs else None
    assertions = [
        _assert("golden_series_length", len(expected) == len(actual), "聚合后的时间点数量必须与 golden series 一致。", len(expected), len(actual)),
        _assert("golden_series_values", max_diff is not None and max_diff <= tolerance, "聚合后的数值必须与 golden series 对齐。", expected, actual, tolerance),
    ]
    result["assertions"] = assertions
    result["aggregationResult"] = {"method": case.expected.get("method", case.request.get("aggregation", {}).get("method", "-")), "maxAbsDiff": max_diff, "comparedPoints": min(len(expected), len(actual)), "expectedSeriesHash": _hash_json(expected), "actualSeriesHash": _hash_json(actual)}
    result["passed"] = _passed(assertions, result.get("runStatus", "failed"))
    result["artifacts"].clear()
    return result


def _metric_for_body(body: dict, model_id: str, metric: str = "mae") -> float | None:
    for model in body.get("rankedModels", []):
        if model.get("modelId") == model_id and model.get("status") == "success":
            value = (model.get("metrics") or {}).get(metric)
            return float(value) if value is not None else None
    return None


def _first_available_feature_model(client: TestClient) -> str | None:
    response = client.get("/api/models")
    if response.status_code != 200:
        return None
    models = {item["id"]: item for item in response.json().get("models", [])}
    for model_id in ["random_forest", "xgboost", "lightgbm"]:
        model = models.get(model_id)
        if model and model.get("availabilityStatus") == "available":
            return model_id
    return None


def _feature_lift_request(model_id: str, feature_enabled: bool, covariate: str = "promo") -> dict:
    model_params = {"nEstimators": 60, "maxDepth": 4, "minSamplesLeaf": 1}
    if model_id == "xgboost":
        model_params = {"nEstimators": 60, "maxDepth": 3, "learningRate": 0.08}
    if model_id == "lightgbm":
        model_params = {"nEstimators": 60, "numLeaves": 15, "learningRate": 0.08}
    return {
        "runId": f"bench_feature_lift_{model_id}_{feature_enabled}_{datetime.now(timezone.utc).timestamp()}",
        "sheetName": "CSV",
        "dataMode": "aggregated",
        "timeColumn": "date",
        "targetColumns": ["value"],
        "covariateColumns": [covariate],
        "covariateConfigs": [{"column": covariate, "type": "known_future", "missingValueStrategy": "ffill"}],
        "aggregation": {"enabled": False, "method": "sum"},
        "frequency": "auto",
        "horizon": 14,
        "testSize": 14,
        "selectedModels": [model_id],
        "modelParameters": {model_id: model_params},
        "featureConfig": {"lagFeatures": True, "rollingFeatures": True, "calendarFeatures": True, "holidayFeatures": False, "covariates": feature_enabled},
        "cleaningConfig": {"preset": "standard"},
        "runProfile": "fast",
        "parameterStrategy": "default",
        "randomSeed": 42,
    }


def _run_uploaded_request(client: TestClient, path: Path, content_type: str, request: dict) -> dict:
    with path.open("rb") as handle:
        upload_response = client.post("/api/upload/preview", files={"file": (path.name, handle, content_type)})
    if upload_response.status_code != 200:
        return {"status": upload_response.status_code, "error": upload_response.text}
    response = client.post("/api/forecast/run", json={**request, "uploadId": upload_response.json()["uploadId"]})
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
    if response.status_code == 200 and body:
        client.delete(f"/api/experiments/{body['experimentId']}")
    return {"status": response.status_code, "body": body, "error": response.text if response.status_code != 200 else None}


def _run_feature_lift_suite(client: TestClient, backend_root: Path) -> list[dict]:
    started = now()
    memory_before = max_rss_mb()
    model_id = _first_available_feature_model(client)
    assertions = []
    result = {"name": "feature_lift_covariate_effect", "suite": "feature_lift", "category": "feature", "fileFormat": "csv", "targetColumns": ["value"], "covariateColumns": ["promo"], "selectedModels": [model_id] if model_id else [], "uploadStatus": "skipped", "runStatus": "skipped", "seconds": 0.0, "memoryMb": 0.0, "warningCount": 0, "modelStatuses": {}, "modelResults": [], "thresholds": {"minImprovementRatio": 0.15, "maxNoiseDegradationRatio": 0.10}, "artifacts": {}}
    if not model_id:
        assertions.append(_assert("feature_model_available", False, "未安装 Random Forest / XGBoost / LightGBM，Feature lift benchmark 记为跳过。", status_if_false="skipped"))
        result["featureLiftResult"] = {"modelId": None}
    else:
        fixture_root = backend_root / "benchmarks" / "fixtures" / "feature_lift"
        positive = fixture_root / "positive_covariate.csv"
        baseline = _run_uploaded_request(client, positive, "text/csv", _feature_lift_request(model_id, False))
        lifted = _run_uploaded_request(client, positive, "text/csv", _feature_lift_request(model_id, True))
        baseline_mae = _metric_for_body(baseline.get("body") or {}, model_id)
        feature_mae = _metric_for_body(lifted.get("body") or {}, model_id)
        improvement = (baseline_mae - feature_mae) / baseline_mae if baseline_mae and feature_mae is not None else None
        assertions.append(_assert("positive_feature_run_success", baseline.get("status") == 200 and lifted.get("status") == 200, "启用/禁用协变量的正例实验都必须运行成功。", 200, {"baseline": baseline.get("status"), "feature": lifted.get("status")}))
        assertions.append(_assert("positive_feature_lift", improvement is not None and improvement >= 0.15, "正例中协变量参入后 MAE 至少改善 15%。", 0.15, improvement))
        noise = fixture_root / "noise_covariate.csv"
        noise_base = _run_uploaded_request(client, noise, "text/csv", _feature_lift_request(model_id, False))
        noise_lift = _run_uploaded_request(client, noise, "text/csv", _feature_lift_request(model_id, True))
        noise_base_mae = _metric_for_body(noise_base.get("body") or {}, model_id)
        noise_feature_mae = _metric_for_body(noise_lift.get("body") or {}, model_id)
        degradation = (noise_feature_mae - noise_base_mae) / noise_base_mae if noise_base_mae and noise_feature_mae is not None else None
        assertions.append(_assert("noise_covariate_not_overclaimed", degradation is None or degradation <= 0.10, "噪声协变量不应造成超过 10% 的性能退化。", 0.10, degradation, status_if_false="warning"))
        leakage_request = _feature_lift_request(model_id, True, "future_truth")
        leakage_request["covariateConfigs"] = [{"column": "future_truth", "type": "unknown_future", "unknownFutureAction": "analysis_only"}]
        leakage = _run_uploaded_request(client, positive, "text/csv", leakage_request)
        manifest = (leakage.get("body") or {}).get("manifest") or {}
        covariates = ((manifest.get("featurePipelines") or [{}])[0]).get("covariates") or []
        leakage_protected = leakage.get("status") == 200 and any(item.get("name") == "future_truth" and item.get("type") == "unknown_future" for item in covariates)
        assertions.append(_assert("unknown_future_analysis_only_documented", leakage_protected, "unknown_future analysis_only 必须进入说明但不得作为可用未来真实值。", True, leakage_protected))
        result["featureLiftResult"] = {"modelId": model_id, "baselineMae": baseline_mae, "featureMae": feature_mae, "improvementRatio": improvement, "noiseDegradationRatio": degradation, "leakageProtected": leakage_protected}
        result["runStatus"] = "200"
        result["uploadStatus"] = "200"
    result["assertions"] = assertions
    result["passed"] = _passed(assertions, result.get("runStatus", "skipped"))
    result["seconds"] = elapsed_seconds(started)
    result["memoryMb"] = max(0.0, round(max_rss_mb() - memory_before, 2))
    return [result]


def _series_hash(detail: dict) -> str:
    return _hash_json([{"time": item.get("time"), "value": round(float(item.get("value", 0.0)), 12)} for item in detail.get("series", [])])


def _run_repro_case(client: TestClient, case, profile: str) -> dict:
    started = now()
    memory_before = max_rss_mb()
    first = _run_forecast_case(client, case, profile, delete=False)
    second = _run_forecast_case(client, case, profile, delete=False)
    assertions = []
    drift: list[str] = []
    ignored = ["runtime elapsed seconds", "memory snapshots", "log timestamps", "experimentId", "experimentName", "createdAt"]
    if first.get("runStatus") != "200" or second.get("runStatus") != "200":
        assertions.append(_assert("rerun_success", False, "两次复现实验必须都运行成功。", 200, {"first": first.get("runStatus"), "second": second.get("runStatus")}))
    else:
        first_body = first["artifacts"]["response"]
        second_body = second["artifacts"]["response"]
        first_manifest = first_body.get("manifest") or {}
        second_manifest = second_body.get("manifest") or {}
        for key in ["datasetHash", "configHash", "featurePipelineVersion", "runtimeEventSchemaVersion", "randomSeed"]:
            ok = first_manifest.get(key) == second_manifest.get(key)
            if not ok:
                drift.append(key)
            assertions.append(_assert(f"manifest_{key}", ok, f"Manifest {key} 必须一致。", first_manifest.get(key), second_manifest.get(key)))
        assertions.append(_assert("aggregated_series_hash", _series_hash(first["artifacts"].get("detail", {})) == _series_hash(second["artifacts"].get("detail", {})), "聚合后的历史序列 hash 必须一致。"))
        metric_tol = float(case.thresholds.get("metricTolerance", 1e-8))
        for model_a, model_b in zip(first_body.get("rankedModels", []), second_body.get("rankedModels", [])):
            if model_a.get("status") != "success" or model_b.get("status") != "success":
                continue
            for metric in ["mae", "mse", "rmse", "wape"]:
                a = (model_a.get("metrics") or {}).get(metric)
                b = (model_b.get("metrics") or {}).get(metric)
                ok = (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) <= metric_tol)
                if not ok:
                    drift.append(f"{model_a.get('modelId')}.{metric}")
                assertions.append(_assert(f"metric_{model_a.get('modelId')}_{metric}", ok, f"{model_a.get('modelId')} {metric} 必须在容差内复现。", a, b, metric_tol))
        assertions.append(_assert("backtest_predictions", _hash_json(first_body.get("backtest")) == _hash_json(second_body.get("backtest")), "backtest predictions/residual 必须一致。"))
        assertions.append(_assert("recommended_model", first_body.get("recommendedModelId") == second_body.get("recommendedModelId"), "推荐模型必须一致。", first_body.get("recommendedModelId"), second_body.get("recommendedModelId")))
    for item in [first, second]:
        if item.get("experimentId"):
            client.delete(f"/api/experiments/{item['experimentId']}")
    score = sum(1 for item in assertions if item.get("status") == "passed") / len(assertions) if assertions else 0.0
    result = _case_result_base(case, elapsed_seconds(started), max_rss_mb() - memory_before)
    result.update({"uploadStatus": "200" if first.get("uploadStatus") == "200" and second.get("uploadStatus") == "200" else "failed", "runStatus": "200" if first.get("runStatus") == "200" and second.get("runStatus") == "200" else "failed", "assertions": assertions, "reproducibilityResult": {"reproducibilityScore": score, "driftItems": drift, "ignoredVolatileFields": ignored, "firstExperimentId": first.get("experimentId"), "secondExperimentId": second.get("experimentId")}})
    result["passed"] = _passed(assertions, result["runStatus"])
    return result


def _run_agent_suite(client: TestClient, mode: str) -> list[dict]:
    started = now()
    memory_before = max_rss_mb()
    correct = valid = leakage_needed = leakage_hit = unsupported_promises = 0
    online_warnings: list[str] = []
    artifacts = {"cases": []}
    for item in AGENT_GOLDEN:
        response = client.post("/api/workbench-agent/ideas/analyze", json={"idea": item["idea"], "context": {"targetColumn": "passenger_count", "frequency": "D", "availableColumns": ["date", "passenger_count"], "horizon": 14, "domain": "aviation"}, "mode": mode})
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        route = body.get("route")
        is_valid = response.status_code == 200 and all(key in body for key in ["route", "confidence", "rationale", "requiredInputs", "leakageWarnings", "nextApiCalls"])
        valid += 1 if is_valid else 0
        correct += 1 if route == item["expectedRoute"] else 0
        if item["needsLeakageWarning"]:
            leakage_needed += 1
            leakage_hit += 1 if body.get("leakageWarnings") else 0
        if route == "unsupported" and body.get("nextApiCalls"):
            unsupported_promises += 1
        online = body.get("onlineObservation")
        if online and online.get("status") in {"not_configured", "failed", "skipped"}:
            online_warnings.append(f"{item['name']}: {online.get('message')}")
        artifacts["cases"].append({"name": item["name"], "expectedRoute": item["expectedRoute"], "actualRoute": route, "status": response.status_code})
    total = len(AGENT_GOLDEN)
    route_accuracy = correct / total if total else 0.0
    schema_validity = valid / total if total else 0.0
    leakage_recall = leakage_hit / leakage_needed if leakage_needed else 1.0
    assertions = [
        _assert("route_accuracy", route_accuracy >= 0.90, "离线黄金集 route accuracy 必须 >= 90%。", 0.90, route_accuracy),
        _assert("schema_validity", schema_validity == 1.0, "Agent 响应 schema validity 必须为 100%。", 1.0, schema_validity),
        _assert("leakage_warning_recall", leakage_recall >= 0.95, "泄漏风险召回率必须 >= 95%。", 0.95, leakage_recall),
        _assert("unsupported_promise_count", unsupported_promises == 0, "unsupported 场景不能承诺后续执行接口。", 0, unsupported_promises),
    ]
    result = {"name": "workbench_agent_golden_routes", "suite": "agent_routing", "category": "agent", "fileFormat": "json", "uploadStatus": "skipped", "runStatus": "200", "seconds": elapsed_seconds(started), "memoryMb": max(0.0, round(max_rss_mb() - memory_before, 2)), "warningCount": len(online_warnings), "assertions": assertions, "artifacts": artifacts, "thresholds": {"routeAccuracy": 0.90, "schemaValidity": 1.0, "leakageWarningRecall": 0.95}, "agentRoutingResult": {"routeAccuracy": route_accuracy, "schemaValidity": schema_validity, "leakageWarningRecall": leakage_recall, "unsupportedPromiseCount": unsupported_promises, "onlineWarnings": online_warnings}}
    result["passed"] = _passed(assertions, "200")
    return [result]


def main() -> None:
    args = _parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    ensure_benchmark_fixtures(backend_root)
    client = TestClient(app)
    selected_suites = SUITE_ALIASES[args.suite]
    started = now()
    results: list[dict] = []
    for case in _selected_cases(backend_root, args):
        if case.suite == "aggregation_correctness":
            results.append(_run_aggregation_case(client, case, args.profile))
        elif case.suite == "reproducibility":
            results.append(_run_repro_case(client, case, args.profile))
        else:
            result = _run_forecast_case(client, case, args.profile)
            result["assertions"] = [_assert("api_run_success", result.get("runStatus") == "200", "Forecast API run must complete successfully.", 200, result.get("runStatus"))]
            result["passed"] = _passed(result["assertions"], result.get("runStatus", "failed"))
            result.get("artifacts", {}).clear()
            results.append(result)
    if "feature_lift" in selected_suites:
        results.extend(_run_feature_lift_suite(client, backend_root))
    if "agent_routing" in selected_suites:
        results.extend(_run_agent_suite(client, args.agent_mode))
    total_cases = len(results)
    successful_runs = sum(1 for result in results if result.get("runStatus") == "200")
    failed_runs = sum(1 for result in results if result.get("runStatus") not in {"200", "skipped"})
    failed_assertions = sum(1 for result in results for assertion in result.get("assertions", []) if assertion.get("status") == "failed")
    warning_assertions = sum(1 for result in results for assertion in result.get("assertions", []) if assertion.get("status") == "warning")
    summary = {"schemaVersion": BENCHMARK_RESULT_SCHEMA_VERSION, "profile": args.profile, "suite": args.suite, "agentMode": args.agent_mode, "generatedAt": datetime.now(timezone.utc).isoformat(), "seconds": elapsed_seconds(started), "totalCases": total_cases, "successfulRuns": successful_runs, "failedRuns": failed_runs, "successRate": successful_runs / total_cases if total_cases else 0.0, "failureRate": failed_runs / total_cases if total_cases else 0.0, "failedAssertions": failed_assertions, "warningAssertions": warning_assertions, "cases": results}
    summary = BenchmarkSummary.model_validate(summary).model_dump(mode="json")
    json_path, md_path = write_summary(backend_root, summary)
    print(f"benchmark summary written to {json_path}")
    print(f"benchmark report written to {md_path}")
    if failed_assertions or failed_runs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
