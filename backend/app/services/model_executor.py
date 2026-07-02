from __future__ import annotations

import multiprocessing as mp
import queue
import logging
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any


ISOLATED_MODEL_IDS = {"timesfm", "xgboost"}
ISOLATED_MODEL_TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


@dataclass
class IsolatedModelResult:
    predictions: list[float]
    lower: list[float | None]
    upper: list[float | None]
    warnings: list[str]
    fit_seconds: float
    predict_seconds: float


def should_isolate_model(model_id: str) -> bool:
    return model_id in ISOLATED_MODEL_IDS


def _isolated_fit_predict_worker(
    result_queue,
    model_id: str,
    parameters: dict[str, Any] | None,
    times: list[datetime],
    values: list[float],
    frequency: str,
    horizon: int,
) -> None:
    try:
        from app.services.model_registry import create_model

        model = create_model(model_id, parameters)
        fit_start = time.perf_counter()
        model.fit(times, values, frequency)
        fit_seconds = time.perf_counter() - fit_start

        predict_start = time.perf_counter()
        output = model.predict(horizon)
        predict_seconds = time.perf_counter() - predict_start
        result_queue.put(
            {
                "ok": True,
                "predictions": [float(value) for value in output.predictions],
                "lower": output.lower or [],
                "upper": output.upper or [],
                "warnings": output.warnings,
                "fit_seconds": fit_seconds,
                "predict_seconds": predict_seconds,
            }
        )
    except BaseException as exc:
        result_queue.put({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})


def run_isolated_fit_predict(
    model_id: str,
    parameters: dict[str, Any] | None,
    times: list[datetime],
    values: list[float],
    frequency: str,
    horizon: int,
    timeout_seconds: int = ISOLATED_MODEL_TIMEOUT_SECONDS,
) -> IsolatedModelResult:
    context = mp.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_isolated_fit_predict_worker,
        args=(result_queue, model_id, parameters, times, values, frequency, horizon),
        daemon=True,
    )
    process.start()
    logger.info(
        "isolated model process started model=%s pid=%s horizon=%s points=%s timeout_seconds=%s",
        model_id,
        process.pid,
        horizon,
        len(values),
        timeout_seconds,
    )
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        logger.error(
            "isolated model timeout model=%s pid=%s horizon=%s points=%s timeout_seconds=%s",
            model_id,
            process.pid,
            horizon,
            len(values),
            timeout_seconds,
        )
        raise RuntimeError(f"{model_id} exceeded {timeout_seconds}s and was stopped.")

    try:
        payload = result_queue.get_nowait()
    except queue.Empty as exc:
        exit_code = process.exitcode
        logger.error(
            "isolated model stopped without result model=%s pid=%s exit_code=%s horizon=%s points=%s",
            model_id,
            process.pid,
            exit_code,
            horizon,
            len(values),
        )
        raise RuntimeError(f"{model_id} stopped unexpectedly with exit code {exit_code}.") from exc
    finally:
        result_queue.close()

    if not payload.get("ok"):
        error = payload.get("error") or f"{model_id} failed in isolated execution."
        child_traceback = payload.get("traceback")
        logger.error("isolated model failed model=%s error=%s\n%s", model_id, error, child_traceback or "")
        raise RuntimeError(error)

    logger.info(
        "isolated model completed model=%s pid=%s fit_seconds=%.4f predict_seconds=%.4f",
        model_id,
        process.pid,
        float(payload["fit_seconds"]),
        float(payload["predict_seconds"]),
    )
    return IsolatedModelResult(
        predictions=payload["predictions"],
        lower=payload["lower"],
        upper=payload["upper"],
        warnings=payload["warnings"],
        fit_seconds=float(payload["fit_seconds"]),
        predict_seconds=float(payload["predict_seconds"]),
    )
