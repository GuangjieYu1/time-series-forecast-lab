from __future__ import annotations

from datetime import datetime

import numpy as np

from app.core.config import get_settings
from app.models.base import ForecastOutput


class TimesFmModel:
    model_id = "timesfm"

    def __init__(self, max_context: int = 512, normalize_inputs: bool = True) -> None:
        self.values: list[float] = []
        self.model = None
        self.api_version = "unknown"
        self.max_context = max_context
        self.normalize_inputs = normalize_inputs

    def fit(self, times: list[datetime], values: list[float], frequency: str) -> None:
        self.values = [float(value) for value in values]
        try:
            import timesfm  # type: ignore
        except Exception as exc:
            raise RuntimeError("TimesFM package is unavailable. Install optional dependencies and allow the first model download.") from exc

        cache_root = get_settings().model_cache_dir
        local_dir = cache_root / "timesfm_local"
        cache_dir = cache_root / "timesfm"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(timesfm, "TimesFM_2p5_200M_torch"):
                self.api_version = "2.5"
                forecast_config = timesfm.configs.ForecastConfig(
                    max_context=min(self.max_context, max(32, len(values))),
                    max_horizon=256,
                    normalize_inputs=self.normalize_inputs,
                )
                repo_id = getattr(timesfm.TimesFM_2p5_200M_torch, "DEFAULT_REPO_ID", "google/timesfm-2.5-200m-pytorch")
                source = local_dir if (local_dir / "model.safetensors").exists() else repo_id
                self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                    source,
                    cache_dir=str(cache_dir),
                    torch_compile=False,
                )
                try:
                    self.model.compile(forecast_config, torch_compile=False)
                except TypeError:
                    self.model.compile(forecast_config)
                return
            if hasattr(timesfm, "TimesFm"):
                self.api_version = "1.x"
                self.model = timesfm.TimesFm(
                    context_len=min(self.max_context, max(32, len(values))),
                    horizon_len=1,
                    input_patch_len=32,
                    output_patch_len=128,
                    num_layers=20,
                    model_dims=1280,
                    backend="cpu",
                )
                self.model.load_from_checkpoint(repo_id="google/timesfm-1.0-200m")
                return
            raise RuntimeError("Installed timesfm package does not expose a supported TimesFM API.")
        except Exception as exc:
            raise RuntimeError(f"TimesFM could not be loaded from cache or remote checkpoint: {exc}") from exc

    def predict(self, horizon: int) -> ForecastOutput:
        if self.model is None:
            raise RuntimeError("TimesFM model was not fitted.")
        try:
            if self.api_version == "2.5":
                forecast, quantiles = self.model.forecast(horizon, [np.asarray(self.values, dtype=float)])
                predictions = [float(value) for value in np.asarray(forecast[0])[:horizon]]
                lower, upper = _prediction_interval(quantiles, horizon)
                return ForecastOutput(predictions=predictions, lower=lower, upper=upper, warnings=[])

            forecast, _ = self.model.forecast([self.values], freq=[0])
            predictions = [float(value) for value in np.asarray(forecast[0])[:horizon]]
            if len(predictions) < horizon:
                predictions.extend([predictions[-1] if predictions else self.values[-1]] * (horizon - len(predictions)))
            return ForecastOutput(predictions=predictions, warnings=[])
        except Exception as exc:
            raise RuntimeError(f"TimesFM prediction failed: {exc}") from exc


def _prediction_interval(quantiles, horizon: int) -> tuple[list[float | None], list[float | None]]:
    if quantiles is None:
        return [None] * horizon, [None] * horizon
    values = np.asarray(quantiles)
    if values.ndim < 3 or values.shape[0] == 0:
        return [None] * horizon, [None] * horizon
    series_quantiles = values[0]
    if series_quantiles.ndim != 2 or min(series_quantiles.shape) < 2:
        return [None] * horizon, [None] * horizon
    if series_quantiles.shape[0] >= horizon:
        per_step_quantiles = series_quantiles[:horizon, :]
    else:
        per_step_quantiles = series_quantiles[:, :horizon].T
    lower = [float(np.nanmin(row)) for row in per_step_quantiles]
    upper = [float(np.nanmax(row)) for row in per_step_quantiles]
    return lower, upper
