"""Read-only parity probe; uses synthetic series and never imports the database."""
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import importlib.metadata
import json
import math
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.build_info import build_info
from app.services.model_registry import create_model, get_model_capabilities


def main():
    packages = {}
    for name in ("numpy", "pandas", "scipy", "statsmodels", "scikit-learn", "prophet", "xgboost", "lightgbm", "httpx", "fastapi"):
        packages[name] = importlib.metadata.version(name)
    available = [item.id for item in get_model_capabilities() if item.availabilityStatus == "available" and item.enabledInMvp]
    times = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(80)]
    values = [100.0 + i * 0.2 + 5 * math.sin(i * 2 * math.pi / 7) for i in range(80)]
    predictions = {}
    for model_id in ("naive", "seasonal_naive", "moving_average", "arima", "ets", "prophet", "random_forest", "xgboost", "lightgbm"):
        model = create_model(model_id)
        model.fit(times, values, "D")
        result = model.predict(5)
        assert len(result.predictions) == 5 and all(math.isfinite(v) for v in result.predictions)
        predictions[model_id] = result.model_dump()
    print(json.dumps({**build_info(), "packages": packages, "availableModels": sorted(available), "syntheticForecasts": predictions}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
