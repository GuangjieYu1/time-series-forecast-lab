from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.constants import APP_VERSION
from app.core.gpu import get_device, get_memory_info
from app.schemas import ExperimentManifest, ForecastRunRequest, TargetResult
from app.services.model_registry import normalize_model_parameters


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_config_hash_payload(request: ForecastRunRequest) -> dict[str, Any]:
    return {
        "dataMode": request.dataMode,
        "sheetName": request.sheetName,
        "timeColumn": request.timeColumn,
        "targetColumns": request.targetColumns,
        "covariateColumns": request.covariateColumns,
        "aggregation": request.aggregation.model_dump(),
        "frequency": request.frequency,
        "horizon": request.horizon,
        "testSize": request.testSize,
        "selectedModels": request.selectedModels,
        "modelParameters": {
            model_id: normalize_model_parameters(model_id, request.modelParameters.get(model_id))
            for model_id in request.selectedModels
        },
        "featureConfig": request.featureConfig.model_dump(),
        "missingValueStrategy": request.missingValueStrategy,
        "fillMissingTimeSteps": request.fillMissingTimeSteps,
        "duplicateTimeStrategy": request.duplicateTimeStrategy,
        "outlierStrategy": request.outlierStrategy,
        "outlierIqrMultiplier": request.outlierIqrMultiplier,
        "trimStrings": request.trimStrings,
        "runProfile": request.runProfile,
        "parameterStrategy": request.parameterStrategy,
        "randomSeed": request.randomSeed,
    }


def compute_config_hash(request: ForecastRunRequest) -> str:
    payload = canonical_json(build_config_hash_payload(request)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    commit = completed.stdout.strip()
    return commit or None


def build_environment_snapshot(repo_root: Path) -> dict[str, Any]:
    memory = get_memory_info()
    return {
        "appVersion": APP_VERSION,
        "gitCommit": get_git_commit(repo_root),
        "pythonVersion": sys.version.split()[0],
        "platform": platform.platform(),
        "device": get_device(),
        "memoryTotalMb": memory.get("memoryTotalMb"),
        "memoryAvailableMb": memory.get("memoryAvailableMb"),
        "modelCapabilityVersions": None,
    }


def build_manifest(
    *,
    experiment_id: str,
    experiment_name: str,
    request: ForecastRunRequest,
    upload_metadata: dict[str, Any],
    input_columns: list[str],
    target_results: list[TargetResult],
    target_contexts: list[dict[str, Any]],
    repo_root: Path,
) -> ExperimentManifest:
    config_hash = compute_config_hash(request)
    environment = build_environment_snapshot(repo_root)
    targets = []
    for result, context in zip(target_results, target_contexts):
        targets.append(
            {
                "targetColumn": result.targetColumn,
                "detectedFrequency": result.detectedFrequency,
                "timeStart": context.get("timeStart"),
                "timeEnd": context.get("timeEnd"),
                "trainStart": context.get("trainStart"),
                "trainEnd": context.get("trainEnd"),
                "testStart": context.get("testStart"),
                "testEnd": context.get("testEnd"),
                "recommendedModelId": result.recommendedModelId,
                "models": [
                    {
                        "modelId": model.modelId,
                        "modelName": model.modelName,
                        "rank": model.rank,
                        "status": model.status,
                        "metrics": model.metrics.model_dump() if model.metrics else None,
                        "runtime": model.runtime.model_dump(),
                        "warnings": model.warnings,
                        "error": model.error,
                        "tuning": model.tuning.model_dump() if model.tuning else None,
                    }
                    for model in result.rankedModels
                ],
            }
        )
    return ExperimentManifest.model_validate(
        {
            "schemaVersion": "0.3",
            "experimentId": experiment_id,
            "experimentName": experiment_name,
            "createdAt": upload_metadata.get("createdAt"),
            "configHash": config_hash,
            "sourceFileSha256": upload_metadata.get("fileSha256"),
            "environment": environment,
            "data": {
                "fileName": upload_metadata.get("fileName"),
                "fileSize": upload_metadata.get("fileSize"),
                "fileSha256": upload_metadata.get("fileSha256"),
                "sheetName": request.sheetName,
                "columns": input_columns,
                "timeColumn": request.timeColumn,
                "targetColumns": request.targetColumns,
                "covariateColumns": request.covariateColumns,
            },
            "configuration": build_config_hash_payload(request),
            "targets": targets,
        }
    )
