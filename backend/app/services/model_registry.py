from __future__ import annotations

import importlib.util

from app.core.config import get_settings
from app.models.arima import ArimaModel
from app.models.ets import EtsModel
from app.models.ml_regression import LightGbmModel, RandomForestTsModel, XGBoostModel
from app.models.moving_average import MovingAverageModel
from app.models.naive import NaiveModel
from app.models.prophet_model import ProphetModel
from app.models.seasonal_naive import SeasonalNaiveModel
from app.models.timesfm_model import TimesFmModel
from app.schemas import ModelCapability


def _module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _timesfm_cache_has_files() -> bool:
    cache_dir = get_settings().model_cache_dir / "timesfm"
    local_file = get_settings().model_cache_dir / "timesfm_local" / "model.safetensors"
    if local_file.exists() and local_file.stat().st_size > 500_000_000:
        return True
    if not cache_dir.exists():
        return False
    return any(path.is_file() and path.name == "model.safetensors" and path.stat().st_size > 500_000_000 for path in cache_dir.rglob("*"))


MODEL_CAPABILITIES: dict[str, ModelCapability] = {
    "naive": ModelCapability(
        id="naive",
        name="Naive",
        category="Baseline",
        shortDescription="Baseline model that repeats the latest observed value.",
        representativePaperTitle=None,
        representativePaperUrl=None,
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=365,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        modelFamily="Baseline",
        priority=1,
    ),
    "seasonal_naive": ModelCapability(
        id="seasonal_naive",
        name="Seasonal Naive",
        category="Baseline",
        shortDescription="Seasonal baseline that repeats values from the previous seasonal cycle.",
        representativePaperTitle=None,
        representativePaperUrl=None,
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=365,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        modelFamily="Baseline",
        priority=2,
    ),
    "moving_average": ModelCapability(
        id="moving_average",
        name="Moving Average",
        category="Baseline",
        shortDescription="Uses the recent rolling average as the future forecast.",
        representativePaperTitle=None,
        representativePaperUrl=None,
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=365,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        modelFamily="Baseline",
        priority=3,
    ),
    "arima": ModelCapability(
        id="arima",
        name="ARIMA",
        category="Statistical",
        shortDescription="Classic autoregressive integrated moving-average model for serial dependence.",
        representativePaperTitle="Time Series Analysis: Forecasting and Control",
        representativePaperUrl="https://www.wiley.com/en-us/Time+Series+Analysis%3A+Forecasting+and+Control%2C+5th+Edition-p-9781118675021",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        modelFamily="Statistical",
        priority=10,
    ),
    "ets": ModelCapability(
        id="ets",
        name="ETS",
        category="Statistical",
        shortDescription="Exponential smoothing family for error, trend, and seasonality behavior.",
        representativePaperTitle="Forecasting with Exponential Smoothing",
        representativePaperUrl="https://robjhyndman.com/expsmooth/",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        modelFamily="Statistical",
        priority=11,
    ),
    "prophet": ModelCapability(
        id="prophet",
        name="Prophet",
        category="Statistical",
        shortDescription="Interpretable additive model for trend and seasonality.",
        representativePaperTitle="Forecasting at Scale",
        representativePaperUrl="https://peerj.com/preprints/3190/",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=365,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        dependencyPackage="prophet",
        installCommand="pip install -r requirements-optional.txt",
        modelFamily="Statistical",
        priority=12,
    ),
    "timesfm": ModelCapability(
        id="timesfm",
        name="TimesFM",
        category="Foundation Model",
        shortDescription="Google time-series foundation model focused on cross-domain zero-shot forecasting.",
        representativePaperTitle="A decoder-only foundation model for time-series forecasting",
        representativePaperUrl="https://arxiv.org/abs/2310.10688",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=256,
        requiresGpu=True,
        isFoundationModel=True,
        enabledInMvp=True,
        modelFamily="Foundation Model",
        priority=30,
    ),
    "xgboost": ModelCapability(
        id="xgboost",
        name="XGBoost",
        category="Machine Learning",
        shortDescription="Gradient-boosted tree regressor using lag, rolling, and calendar features for recursive forecasting.",
        representativePaperTitle="XGBoost: A Scalable Tree Boosting System",
        representativePaperUrl="https://arxiv.org/abs/1603.02754",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        dependencyPackage="xgboost",
        installCommand="pip install xgboost",
        paperTitle="XGBoost: A Scalable Tree Boosting System",
        paperUrl="https://arxiv.org/abs/1603.02754",
        modelFamily="Machine Learning",
        priority=40,
    ),
    "lightgbm": ModelCapability(
        id="lightgbm",
        name="LightGBM",
        category="Machine Learning",
        shortDescription="LightGBM regressor using lag, rolling, and calendar features for recursive forecasting.",
        representativePaperTitle="LightGBM: A Highly Efficient Gradient Boosting Decision Tree",
        representativePaperUrl="https://papers.nips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        dependencyPackage="lightgbm",
        installCommand="pip install lightgbm",
        paperTitle="LightGBM: A Highly Efficient Gradient Boosting Decision Tree",
        paperUrl="https://papers.nips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html",
        modelFamily="Machine Learning",
        priority=41,
    ),
    "random_forest": ModelCapability(
        id="random_forest",
        name="Random Forest Regressor",
        category="Machine Learning",
        shortDescription="Random forest regressor using lag, rolling, and calendar features for recursive forecasting.",
        representativePaperTitle="Random Forests",
        representativePaperUrl="https://link.springer.com/article/10.1023/A:1010933404324",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        isFoundationModel=False,
        enabledInMvp=True,
        dependencyPackage="scikit-learn",
        installCommand="pip install scikit-learn",
        paperTitle="Random Forests",
        paperUrl="https://link.springer.com/article/10.1023/A:1010933404324",
        modelFamily="Machine Learning",
        priority=42,
    ),
    "nbeats": ModelCapability(
        id="nbeats",
        name="N-BEATS",
        category="Deep Learning",
        shortDescription="Deep neural basis expansion model for univariate time-series forecasting. Planned adapter.",
        representativePaperTitle="N-BEATS: Neural basis expansion analysis for interpretable time series forecasting",
        representativePaperUrl="https://arxiv.org/abs/1905.10437",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned model. Adapter is not connected in v0.2.",
        modelFamily="Deep Learning",
        priority=60,
    ),
    "nhits": ModelCapability(
        id="nhits",
        name="N-HiTS",
        category="Deep Learning",
        shortDescription="Hierarchical interpolation deep forecasting model. Planned adapter.",
        representativePaperTitle="N-HiTS: Neural Hierarchical Interpolation for Time Series Forecasting",
        representativePaperUrl="https://arxiv.org/abs/2201.12886",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=120,
        requiresGpu=False,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned model. Adapter is not connected in v0.2.",
        modelFamily="Deep Learning",
        priority=61,
    ),
    "patchtst": ModelCapability(
        id="patchtst",
        name="PatchTST",
        category="Deep Learning",
        shortDescription="Patch-based Transformer architecture for long-horizon time-series forecasting. Planned adapter.",
        representativePaperTitle="A Time Series is Worth 64 Words: Long-term Forecasting with Transformers",
        representativePaperUrl="https://arxiv.org/abs/2211.14730",
        supportsUnivariate=True,
        supportsMultipleTargets=True,
        supportsCovariates=False,
        supportsPredictionInterval=False,
        minHorizon=1,
        maxHorizon=336,
        requiresGpu=True,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned model. Adapter is not connected in v0.2.",
        modelFamily="Deep Learning",
        priority=62,
    ),
    "chronos": ModelCapability(
        id="chronos",
        name="Chronos",
        category="Foundation Model",
        shortDescription="Amazon time-series foundation model family. Planned adapter.",
        representativePaperTitle="Chronos: Learning the Language of Time Series",
        representativePaperUrl="https://arxiv.org/abs/2403.07815",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=False,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=256,
        requiresGpu=True,
        isFoundationModel=True,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned foundation model. Adapter is not connected in v0.2.",
        modelFamily="Foundation Model",
        priority=70,
    ),
    "moirai": ModelCapability(
        id="moirai",
        name="Moirai",
        category="Foundation Model",
        shortDescription="Salesforce time-series foundation model. Planned adapter.",
        representativePaperTitle="Unified Training of Universal Time Series Forecasting Transformers",
        representativePaperUrl="https://arxiv.org/abs/2402.02592",
        supportsUnivariate=True,
        supportsMultipleTargets=True,
        supportsCovariates=True,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=256,
        requiresGpu=True,
        isFoundationModel=True,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned foundation model. Adapter is not connected in v0.2.",
        modelFamily="Foundation Model",
        priority=71,
    ),
    "lag_llama": ModelCapability(
        id="lag_llama",
        name="Lag-Llama",
        category="Foundation Model",
        shortDescription="Llama-style probabilistic forecasting model for time series. Planned adapter.",
        representativePaperTitle="Lag-Llama: Towards Foundation Models for Probabilistic Time Series Forecasting",
        representativePaperUrl="https://arxiv.org/abs/2310.08278",
        supportsUnivariate=True,
        supportsMultipleTargets=False,
        supportsCovariates=True,
        supportsPredictionInterval=True,
        minHorizon=1,
        maxHorizon=256,
        requiresGpu=True,
        isFoundationModel=True,
        enabledInMvp=False,
        installStatus="planned",
        availabilityStatus="unavailable",
        unavailableReason="Planned foundation model. Adapter is not connected in v0.2.",
        modelFamily="Foundation Model",
        priority=72,
    ),
}


MODEL_FACTORIES = {
    "naive": NaiveModel,
    "seasonal_naive": SeasonalNaiveModel,
    "moving_average": MovingAverageModel,
    "arima": ArimaModel,
    "ets": EtsModel,
    "prophet": ProphetModel,
    "timesfm": TimesFmModel,
    "xgboost": XGBoostModel,
    "lightgbm": LightGbmModel,
    "random_forest": RandomForestTsModel,
}


def get_model_capabilities() -> list[ModelCapability]:
    models = []
    for capability in MODEL_CAPABILITIES.values():
        item = capability.model_copy(deep=True)
        if item.id == "prophet" and not _module_available("prophet"):
            item.availabilityStatus = "unavailable"
            item.installStatus = "not_installed"
            item.dependencyPackage = "prophet"
            item.installCommand = "pip install -r requirements-optional.txt"
            item.unavailableReason = "Install optional dependency 'prophet' to enable this model."
        if item.id == "timesfm" and not _module_available("timesfm"):
            item.availabilityStatus = "unavailable"
            item.installStatus = "not_installed"
            item.dependencyPackage = "timesfm"
            item.installCommand = "pip install -r requirements-optional.txt"
            item.unavailableReason = "Install optional dependency 'timesfm' and allow first checkpoint download."
        elif item.id == "timesfm" and not _timesfm_cache_has_files():
            item.availabilityStatus = "downloading"
            item.installStatus = "downloading"
            item.unavailableReason = "TimesFM is installed. First run may download the checkpoint into backend/.model_cache."
        if item.id == "xgboost" and not _module_available("xgboost"):
            item.availabilityStatus = "unavailable"
            item.installStatus = "not_installed"
            item.unavailableReason = "Install optional dependency 'xgboost' to enable this model."
        if item.id == "lightgbm" and not _module_available("lightgbm"):
            item.availabilityStatus = "unavailable"
            item.installStatus = "not_installed"
            item.unavailableReason = "Install optional dependency 'lightgbm' to enable this model."
        if item.id == "random_forest" and not _module_available("sklearn"):
            item.availabilityStatus = "unavailable"
            item.installStatus = "not_installed"
            item.unavailableReason = "Install optional dependency 'scikit-learn' to enable this model."
        models.append(item)
    return sorted(models, key=lambda model: model.priority)


def get_model_capability(model_id: str) -> ModelCapability | None:
    return MODEL_CAPABILITIES.get(model_id)


def create_model(model_id: str):
    factory = MODEL_FACTORIES.get(model_id)
    if factory is None:
        raise ValueError(f"Unknown model id: {model_id}")
    return factory()


def validate_horizon(selected_models: list[str], horizon: int) -> tuple[int, int]:
    capabilities = [MODEL_CAPABILITIES[model_id] for model_id in selected_models if model_id in MODEL_CAPABILITIES]
    if not capabilities:
        raise ValueError("Select at least one supported model.")
    allowed_min = max(model.minHorizon for model in capabilities)
    allowed_max = min(model.maxHorizon for model in capabilities)
    if allowed_min > allowed_max:
        raise ValueError("Selected models have incompatible horizon ranges.")
    if horizon < allowed_min or horizon > allowed_max:
        raise ValueError(f"Current selected models support horizon {allowed_min} to {allowed_max}.")
    return allowed_min, allowed_max
