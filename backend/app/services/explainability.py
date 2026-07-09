from __future__ import annotations

from typing import Any

import numpy as np

from app.schemas import (
    ExperimentExplainabilityResponse,
    ExplainabilityFeatureItem,
    ExplainabilityModelSummary,
    ExplainabilitySinglePoint,
    ExplainabilitySinglePointContribution,
)
from app.services.model_registry import MODEL_CAPABILITIES


TREE_MODEL_IDS = {"lightgbm", "xgboost", "random_forest"}
SHAP_UNAVAILABLE_WARNING = "SHAP disabled because package is unavailable"


def normalize_feature_key(name: str) -> str:
    lowered = str(name or "").strip().lower()
    normalized = "".join(character for character in lowered if character.isalnum())
    return {
        "dayofweek": "weekday",
        "timeofdayweek": "weekday",
    }.get(normalized, normalized)


def build_default_explainability(model_id: str, model_name: str, target_column: str) -> dict[str, Any]:
    supported = model_id in TREE_MODEL_IDS
    return ExplainabilityModelSummary(
        modelId=model_id,
        modelName=model_name,
        targetColumn=target_column,
        supported=supported,
        warning=None if supported else "当前模型暂不支持 SHAP",
        featureImportance=[],
        shapSupported=False,
        shapWarning=None if supported else "当前模型暂不支持 SHAP",
        shapTopFeatures=[],
        singlePoint=None,
    ).model_dump(mode="json")


def build_tree_explainability_artifact(
    *,
    model_id: str,
    model_name: str,
    target_column: str,
    estimator: Any,
    feature_names: list[str],
    feature_matrix: np.ndarray,
    prediction_feature_rows: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    if model_id not in TREE_MODEL_IDS:
        return build_default_explainability(model_id, model_name, target_column)

    importance_items = _native_feature_importance(estimator, feature_names)
    shap_supported, shap_warning, shap_items, prediction_rows = _shap_artifact(
        estimator=estimator,
        feature_names=feature_names,
        feature_matrix=feature_matrix,
        prediction_feature_rows=prediction_feature_rows or [],
    )
    return {
        "modelId": model_id,
        "modelName": model_name,
        "targetColumn": target_column,
        "supported": True,
        "warning": None,
        "featureImportance": [item.model_dump(mode="json") for item in importance_items],
        "shapSupported": shap_supported,
        "shapWarning": shap_warning,
        "shapTopFeatures": [item.model_dump(mode="json") for item in shap_items],
        "_predictionRows": prediction_rows,
    }


def finalize_tree_explainability_artifact(raw: dict[str, Any], model_points: list[Any]) -> dict[str, Any]:
    payload = dict(raw)
    prediction_rows = payload.pop("_predictionRows", []) or []
    single_point = _single_point_summary(prediction_rows, model_points)
    summary = ExplainabilityModelSummary.model_validate(
        {
            **payload,
            "singlePoint": single_point.model_dump(mode="json") if single_point else None,
        }
    )
    return summary.model_dump(mode="json")


def load_experiment_explainability(
    experiment_id: str,
    recommended_model_id: str | None,
    model_logs: list[dict[str, Any]],
) -> ExperimentExplainabilityResponse:
    summaries: list[ExplainabilityModelSummary] = []
    for row in model_logs:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("modelId") or "")
        if not model_id:
            continue
        capability = MODEL_CAPABILITIES.get(model_id)
        model_name = str(row.get("modelName") or (capability.name if capability else model_id))
        target_column = str(row.get("targetColumn") or "target")
        raw = row.get("explainability")
        if isinstance(raw, dict):
            summaries.append(ExplainabilityModelSummary.model_validate(raw))
        else:
            summaries.append(
                ExplainabilityModelSummary.model_validate(
                    build_default_explainability(model_id, model_name, target_column)
                )
            )
    summaries.sort(key=lambda item: (0 if item.modelId == recommended_model_id else 1, item.modelName.lower()))
    return ExperimentExplainabilityResponse(
        experimentId=experiment_id,
        recommendedModelId=recommended_model_id,
        models=summaries,
    )


def attribution_index(model_logs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    index: dict[tuple[str, str], dict[str, float]] = {}
    for row in model_logs:
        if not isinstance(row, dict):
            continue
        target_column = str(row.get("targetColumn") or "target")
        raw = row.get("explainability")
        if not isinstance(raw, dict):
            continue
        try:
            summary = ExplainabilityModelSummary.model_validate(raw)
        except Exception:
            continue
        for item in summary.featureImportance:
            key = (target_column, normalize_feature_key(item.feature))
            bucket = index.setdefault(key, {})
            if item.importance is not None:
                bucket["importance"] = max(bucket.get("importance", float("-inf")), float(item.importance))
        for item in summary.shapTopFeatures:
            key = (target_column, normalize_feature_key(item.feature))
            bucket = index.setdefault(key, {})
            if item.meanAbsShap is not None:
                bucket["shap"] = max(bucket.get("shap", float("-inf")), float(item.meanAbsShap))
    return {
        key: {
            metric_name: metric_value
            for metric_name, metric_value in metrics.items()
            if metric_value != float("-inf")
        }
        for key, metrics in index.items()
    }


def _native_feature_importance(estimator: Any, feature_names: list[str]) -> list[ExplainabilityFeatureItem]:
    raw_values = getattr(estimator, "feature_importances_", None)
    if raw_values is None and hasattr(estimator, "get_booster"):
        booster = estimator.get_booster()
        score_map = booster.get_score(importance_type="gain")
        raw_values = [float(score_map.get(f"f{index}", 0.0)) for index in range(len(feature_names))]
    if raw_values is None:
        return []
    values = np.asarray(raw_values, dtype=float)
    if values.ndim == 0:
        values = values.reshape(1)
    if not len(values):
        return []
    total = float(np.sum(values))
    order = list(np.argsort(values)[::-1][:20])
    items: list[ExplainabilityFeatureItem] = []
    for rank, index in enumerate(order, start=1):
        value = float(values[index])
        items.append(
            ExplainabilityFeatureItem(
                feature=feature_names[index] if index < len(feature_names) else f"feature_{index}",
                importance=(value / total) if total > 0 else value,
                rank=rank,
            )
        )
    return items


def _shap_artifact(
    *,
    estimator: Any,
    feature_names: list[str],
    feature_matrix: np.ndarray,
    prediction_feature_rows: list[dict[str, float]],
) -> tuple[bool, str | None, list[ExplainabilityFeatureItem], list[dict[str, Any]]]:
    try:
        import shap  # type: ignore
    except Exception:
        return False, SHAP_UNAVAILABLE_WARNING, [], []

    try:
        matrix = np.asarray(feature_matrix, dtype=float)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.size == 0 or matrix.shape[1] == 0:
            return False, "SHAP disabled because feature matrix is empty", [], []
        sample = matrix[-min(len(matrix), 128) :]
        explainer = shap.TreeExplainer(estimator)
        shap_values = _as_2d_array(explainer.shap_values(sample))
        mean_abs = np.mean(np.abs(shap_values), axis=0)
        mean_signed = np.mean(shap_values, axis=0)
        order = list(np.argsort(mean_abs)[::-1][:20])
        items: list[ExplainabilityFeatureItem] = []
        for rank, index in enumerate(order, start=1):
            direction = "neutral"
            if mean_signed[index] > 1e-9:
                direction = "positive"
            elif mean_signed[index] < -1e-9:
                direction = "negative"
            items.append(
                ExplainabilityFeatureItem(
                    feature=feature_names[index] if index < len(feature_names) else f"feature_{index}",
                    meanAbsShap=float(mean_abs[index]),
                    rank=rank,
                    direction=direction,
                )
            )

        prediction_rows: list[dict[str, Any]] = []
        if prediction_feature_rows:
            prediction_matrix = np.asarray(
                [[float(row.get(name, 0.0)) for name in feature_names] for row in prediction_feature_rows],
                dtype=float,
            )
            prediction_shap = _as_2d_array(explainer.shap_values(prediction_matrix))
            for row_values, row_shap in zip(prediction_feature_rows, prediction_shap):
                row_order = list(np.argsort(np.abs(row_shap))[::-1][:5])
                prediction_rows.append(
                    {
                        "contributions": [
                            ExplainabilitySinglePointContribution(
                                feature=feature_names[index] if index < len(feature_names) else f"feature_{index}",
                                value=_safe_float(row_values.get(feature_names[index] if index < len(feature_names) else "")),
                                shapValue=float(row_shap[index]),
                                direction="positive" if row_shap[index] > 1e-9 else "negative" if row_shap[index] < -1e-9 else "neutral",
                            ).model_dump(mode="json")
                            for index in row_order
                        ]
                    }
                )
        return True, None, items, prediction_rows
    except Exception as exc:
        return False, f"SHAP disabled because {exc}", [], []


def _single_point_summary(prediction_rows: list[dict[str, Any]], model_points: list[Any]) -> ExplainabilitySinglePoint | None:
    if not model_points:
        return None
    best_index = max(range(len(model_points)), key=lambda index: abs(_point_value(model_points[index], "residual")))
    point = model_points[best_index]
    contributions = []
    warnings: list[str] = []
    if best_index < len(prediction_rows):
        contributions = [
            ExplainabilitySinglePointContribution.model_validate(item)
            for item in prediction_rows[best_index].get("contributions") or []
            if isinstance(item, dict)
        ]
    if not contributions:
        warnings.append("当前模型未持久化该回测点的 SHAP 贡献明细。")
    return ExplainabilitySinglePoint(
        time=str(_point_attr(point, "time")),
        actual=_point_value(point, "actual"),
        predicted=_point_value(point, "predicted"),
        residual=_point_value(point, "residual"),
        absoluteError=_point_value(point, "absoluteError"),
        contributions=contributions,
        warnings=warnings,
    )


def _point_attr(point: Any, field: str) -> Any:
    if isinstance(point, dict):
        return point.get(field)
    return getattr(point, field, None)


def _point_value(point: Any, field: str) -> float:
    value = _point_attr(point, field)
    return float(value) if value is not None else 0.0


def _as_2d_array(values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 3:
        array = array[0]
    if array.ndim == 1:
        array = array.reshape(1, -1)
    return array


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None
