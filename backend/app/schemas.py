from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.constants import DEFAULT_RANDOM_SEED


class ColumnProfile(BaseModel):
    name: str
    inferredType: Literal["datetime", "number", "boolean", "string", "empty"]
    sampleValues: list[Any] = Field(default_factory=list)
    nonNullCountInPreview: int
    nullCountInPreview: int


class SheetPreview(BaseModel):
    sheetName: str
    rowCountApprox: int | None
    columns: list[ColumnProfile]
    previewRows: list[dict[str, Any]]


class UploadPreviewResponse(BaseModel):
    uploadId: str
    fileName: str
    fileSize: int
    fileSha256: str
    sheets: list[SheetPreview]


class ParsedDateTime(BaseModel):
    ok: bool
    value: datetime | None
    source_format: str | None
    warning: str | None = None


class ModelCapability(BaseModel):
    id: str
    name: str
    category: str
    shortDescription: str
    representativePaperTitle: str | None = None
    representativePaperUrl: str | None = None
    supportsUnivariate: bool
    supportsMultipleTargets: bool
    supportsCovariates: bool
    supportsPredictionInterval: bool
    minHorizon: int
    maxHorizon: int
    requiresGpu: bool
    isFoundationModel: bool = False
    enabledInMvp: bool
    availabilityStatus: Literal["available", "downloading", "unavailable"] = "available"
    unavailableReason: str | None = None
    installStatus: Literal["available", "not_installed", "downloading", "planned", "failed"] = "available"
    dependencyPackage: str | None = None
    installCommand: str | None = None
    paperTitle: str | None = None
    paperUrl: str | None = None
    modelFamily: str = "Baseline"
    priority: int = 100


class ModelsResponse(BaseModel):
    models: list[ModelCapability]


class AggregationConfig(BaseModel):
    enabled: bool = False
    method: Literal["sum", "mean", "count", "max", "min"] = "sum"


class FeatureConfig(BaseModel):
    lagFeatures: bool = True
    rollingFeatures: bool = True
    calendarFeatures: bool = True
    holidayFeatures: bool = True
    covariates: bool = True


CleaningPreset = Literal["conservative", "standard", "strict", "custom"]
MissingValueStrategy = Literal["drop", "zero", "ffill", "bfill", "interpolate", "time", "median"]
OutlierStrategy = Literal["none", "clip_iqr", "hampel"]


class CleaningConfig(BaseModel):
    preset: CleaningPreset = "standard"
    sortByTime: bool = True
    invalidTimeStrategy: Literal["drop", "error"] = "drop"
    trimStrings: bool = True
    normalizeThousandsSeparators: bool = True
    missingValueStrategy: MissingValueStrategy = "time"
    interpolationLimit: int | None = Field(default=3, ge=1, le=365)
    fillMissingTimeSteps: bool = True
    duplicateTimeStrategy: Literal["mean", "sum", "first", "last"] = "mean"
    outlierStrategy: OutlierStrategy = "none"
    outlierIqrMultiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    hampelWindow: int = Field(default=7, ge=3, le=101)
    hampelSigma: float = Field(default=3.0, ge=1.0, le=10.0)

    @model_validator(mode="before")
    @classmethod
    def apply_preset(cls, value):
        if not isinstance(value, dict):
            return value
        preset = value.get("preset", "standard")
        presets = {
            "conservative": {"missingValueStrategy": "drop", "interpolationLimit": None, "fillMissingTimeSteps": False, "outlierStrategy": "none"},
            "standard": {"missingValueStrategy": "time", "interpolationLimit": 3, "fillMissingTimeSteps": True, "outlierStrategy": "none"},
            "strict": {"missingValueStrategy": "time", "interpolationLimit": 7, "fillMissingTimeSteps": True, "outlierStrategy": "hampel"},
            "custom": {},
        }
        return {**presets.get(preset, {}), **value}


class HolidayConfig(BaseModel):
    enabled: bool = True
    countryCode: str = "CN"
    subdivision: str | None = None
    observed: bool = True
    windowDays: int = Field(default=1, ge=0, le=30)


class CovariateConfig(BaseModel):
    column: str
    type: Literal["known_future", "static", "unknown_future"] = "static"
    unknownFutureAction: Literal["analysis_only", "forecast"] = "analysis_only"
    forecastMode: Literal["auto", "manual", "per_primary_model"] = "auto"
    manualModelId: Literal["naive", "seasonal_naive", "arima", "ets"] | None = None
    missingValueStrategy: MissingValueStrategy = "ffill"


class ForecastRunRequest(BaseModel):
    runId: str | None = None
    uploadId: str
    sheetName: str
    dataMode: Literal["aggregated", "raw"]
    timeColumn: str
    targetColumns: list[str]
    covariateColumns: list[str] = Field(default_factory=list)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    frequency: str = "auto"
    horizon: int = Field(ge=1)
    testSize: int = Field(ge=1)
    selectedModels: list[str]
    modelParameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    featureConfig: FeatureConfig = Field(default_factory=FeatureConfig)
    cleaningConfig: CleaningConfig | None = None
    covariateConfigs: list[CovariateConfig] = Field(default_factory=list)
    holidayConfig: HolidayConfig = Field(default_factory=HolidayConfig)
    missingValueStrategy: MissingValueStrategy = "drop"
    fillMissingTimeSteps: bool = True
    duplicateTimeStrategy: Literal["mean", "sum", "first", "last"] = "mean"
    outlierStrategy: OutlierStrategy = "none"
    outlierIqrMultiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    trimStrings: bool = True
    runProfile: Literal["fast", "balanced", "accurate"] = "balanced"
    parameterStrategy: Literal["default", "auto"] = "default"
    randomSeed: int = DEFAULT_RANDOM_SEED
    experimentName: str | None = None

    @model_validator(mode="after")
    def normalize_cleaning_config(self):
        if self.cleaningConfig is None:
            self.cleaningConfig = CleaningConfig(
                preset="custom",
                trimStrings=self.trimStrings,
                missingValueStrategy=self.missingValueStrategy,
                fillMissingTimeSteps=self.fillMissingTimeSteps,
                duplicateTimeStrategy=self.duplicateTimeStrategy,
                outlierStrategy=self.outlierStrategy,
                outlierIqrMultiplier=self.outlierIqrMultiplier,
            )
        else:
            self.missingValueStrategy = self.cleaningConfig.missingValueStrategy
            self.fillMissingTimeSteps = self.cleaningConfig.fillMissingTimeSteps
            self.duplicateTimeStrategy = self.cleaningConfig.duplicateTimeStrategy
            self.outlierStrategy = self.cleaningConfig.outlierStrategy
            self.outlierIqrMultiplier = self.cleaningConfig.outlierIqrMultiplier
            self.trimStrings = self.cleaningConfig.trimStrings
        return self


class RuntimeEstimateRequest(BaseModel):
    rowCount: int = Field(ge=1)
    frequency: str = "auto"
    totalColumnCount: int = Field(default=1, ge=1)
    targetCount: int = Field(default=1, ge=1)
    covariateCount: int = Field(default=0, ge=0)
    unknownFutureForecastCount: int = Field(default=0, ge=0)
    perPrimaryModelCovariateCount: int = Field(default=0, ge=0)
    featureConfig: FeatureConfig = Field(default_factory=FeatureConfig)
    runProfile: Literal["fast", "balanced", "accurate"] = "balanced"
    parameterStrategy: Literal["default", "auto"] = "default"
    device: str = "cpu"
    selectedModels: list[str]


class MetricValues(BaseModel):
    mae: float | None = None
    mse: float | None = None
    rmse: float | None = None
    wape: float | None = None


class TuningTrial(BaseModel):
    round: int
    params: dict[str, Any] = Field(default_factory=dict)
    status: Literal["running", "success", "failed", "pruned"] = "success"
    metrics: MetricValues | None = None
    elapsedSeconds: float = 0.0
    selected: bool = False
    message: str | None = None


class ModelRuntime(BaseModel):
    fitSeconds: float = 0.0
    predictSeconds: float = 0.0


class ModelTuning(BaseModel):
    enabled: bool
    profile: Literal["fast", "balanced", "accurate"]
    strategy: Literal["default", "auto"]
    strategyLabel: str = "Default Parameters"
    sampler: str | None = None
    pruner: str | None = None
    selectedParams: dict[str, Any] = Field(default_factory=dict)
    candidateCount: int = 0
    bestMetric: float | None = None
    tuningSeconds: float = 0.0
    candidateLimit: int = 0
    timeBudgetSeconds: float = 0.0
    validationSize: int = 0
    stoppedEarly: bool = False
    trials: list[TuningTrial] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RankedModel(BaseModel):
    modelId: str
    modelName: str
    rank: int | None = None
    metrics: MetricValues | None = None
    runtime: ModelRuntime
    status: Literal["success", "failed"] = "success"
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    tuning: ModelTuning | None = None


class BacktestActualPoint(BaseModel):
    time: str
    value: float


class BacktestPredictionPoint(BaseModel):
    time: str
    predicted: float
    actual: float
    residual: float
    absoluteError: float
    squaredError: float


class BacktestData(BaseModel):
    actual: list[BacktestActualPoint]
    predictions: dict[str, list[BacktestPredictionPoint]]


class Diagnostics(BaseModel):
    originalRowCount: int
    validRowCount: int
    droppedRowCount: int
    duplicateTimeCount: int
    missingTimeCount: int
    invalidTimeCount: int = 0
    inputMissingTargetCount: int = 0
    invalidTargetCount: int = 0
    filledValueCount: int = 0
    outlierCount: int = 0
    outlierAdjustedCount: int = 0
    cleaningActions: list[str] = Field(default_factory=list)
    timeStart: str | None
    timeEnd: str | None
    warnings: list[str] = Field(default_factory=list)


class DataHealthDiagnostics(BaseModel):
    frequency: str | None = None
    validPointCount: int
    trainPointCount: int
    testPointCount: int
    originalRowCount: int
    droppedRowRate: float
    invalidTimeRate: float
    targetMissingRate: float
    duplicateTimeRate: float
    missingTimeRate: float
    outlierRate: float
    continuityCoverage: float
    timeContinuous: bool
    trainSizeSufficient: bool
    testSizeReasonable: bool
    timeStart: str | None = None
    timeEnd: str | None = None
    timeSpanDays: float | None = None


class DataHealthReport(BaseModel):
    score: int = Field(ge=0, le=100)
    level: Literal["excellent", "good", "fair", "poor"]
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    diagnostics: DataHealthDiagnostics


class TargetResult(BaseModel):
    targetColumn: str
    detectedFrequency: str
    recommendedModelId: str | None
    rankedModels: list[RankedModel]
    backtest: BacktestData
    diagnostics: Diagnostics
    dataHealth: DataHealthReport


class ForecastRunResponse(BaseModel):
    experimentId: str
    targetColumn: str
    detectedFrequency: str
    horizon: int
    testSize: int
    recommendedModelId: str | None
    rankedModels: list[RankedModel]
    backtest: BacktestData
    diagnostics: Diagnostics
    dataHealth: DataHealthReport
    targetResults: list[TargetResult]
    manifest: ExperimentManifest | None = None


class FinalForecastRequest(BaseModel):
    runId: str | None = None
    experimentId: str
    finalModelId: str
    horizon: int = Field(ge=1)


class ForecastPoint(BaseModel):
    time: str
    predicted: float
    lower: float | None = None
    upper: float | None = None


class HistoryPoint(BaseModel):
    time: str
    value: float


class FinalForecastResponse(BaseModel):
    experimentId: str
    finalModelId: str
    history: list[HistoryPoint]
    forecast: list[ForecastPoint]
    modelInfo: dict[str, Any]


class ModelProgress(BaseModel):
    modelId: str
    modelName: str
    targetColumn: str
    status: Literal["queued", "tuning", "fitting", "predicting", "scoring", "success", "failed"] = "queued"
    percent: int = Field(default=0, ge=0, le=100)
    message: str = "Waiting to run."
    fitSeconds: float | None = None
    predictSeconds: float | None = None
    error: str | None = None


class ForecastProgress(BaseModel):
    runId: str
    kind: Literal["backtest", "final"]
    status: Literal["running", "completed", "failed"]
    phase: str
    overallPercent: int = Field(ge=0, le=100)
    message: str
    currentTarget: str | None = None
    completedModels: int = 0
    totalModels: int = 0
    models: list[ModelProgress] = Field(default_factory=list)
    startedAt: datetime
    updatedAt: datetime
    error: str | None = None
    version: int = 1


RuntimeStageId = Literal[
    "pending",
    "loading",
    "cleaning",
    "feature_engineering",
    "feature_selection",
    "auto_tuning",
    "training",
    "forecast",
    "residual_analysis",
    "finished",
    "failed",
]

RuntimeStepStatus = Literal["pending", "running", "completed", "failed"]
FeatureStepStatus = Literal["pending", "running", "completed", "skipped", "failed"]


class RuntimeStateStep(BaseModel):
    id: RuntimeStageId
    label: str
    status: RuntimeStepStatus = "pending"
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    elapsedSeconds: float | None = None


class RuntimeResourceSnapshot(BaseModel):
    device: str = "cpu"
    memoryTotalMb: int | None = None
    memoryAvailableMb: int | None = None
    memoryUsedMb: float | None = None
    cpuPercent: float | None = None
    threadCount: int | None = None
    gpuLabel: str | None = None


class AcceleratorInfo(BaseModel):
    hardwareDetected: bool = False
    runtimeAvailable: bool = False
    type: Literal["nvidia", "mps"] | None = None
    name: str | None = None
    memoryTotalMb: int | None = None
    driverVersion: str | None = None
    frameworkVersion: str | None = None
    frameworkBuild: str | None = None
    cudaRuntime: str | None = None
    reason: str | None = None


class DeviceInfoResponse(BaseModel):
    device: Literal["cuda", "mps", "cpu"] = "cpu"
    memoryTotalMb: int | None = None
    memoryAvailableMb: int | None = None
    accelerator: AcceleratorInfo = Field(default_factory=AcceleratorInfo)


class RuntimeLogEntry(BaseModel):
    id: str
    timestamp: datetime
    stage: RuntimeStageId
    level: Literal["info", "warn", "error", "success"] = "info"
    message: str
    modelId: str | None = None
    modelName: str | None = None
    targetColumn: str | None = None
    metricLabel: str | None = None
    metricValue: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RuntimeTimelineEntry(BaseModel):
    id: str
    timestamp: datetime
    stage: RuntimeStageId
    label: str
    status: RuntimeStepStatus
    level: Literal["info", "warn", "error", "success"] = "info"
    message: str | None = None
    modelId: str | None = None
    modelName: str | None = None
    targetColumn: str | None = None
    overallPercent: int | None = None


class RuntimeEvent(BaseModel):
    schemaVersion: Literal["0.4"] = "0.4"
    id: str
    sequence: int = Field(ge=1)
    runId: str
    timestamp: datetime
    eventType: Literal["stage", "model", "resource", "feature", "optimization", "log", "terminal"]
    stage: RuntimeStageId
    status: RuntimeStepStatus
    message: str
    modelId: str | None = None
    targetColumn: str | None = None
    progressPercent: int | None = Field(default=None, ge=0, le=100)
    metricLabel: str | None = None
    metricValue: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)



class RuntimeFeatureFamily(BaseModel):
    id: Literal["target", "lag", "rolling", "calendar", "holiday", "covariates"]
    label: str
    enabled: bool = True
    generatedCount: int = 0
    selectedCount: int = 0
    importantCount: int = 0


class RuntimeFeatureNode(BaseModel):
    id: str
    name: str
    source: str
    formula: str
    family: str
    lifecycle: Literal["generated", "selected", "dropped", "used", "important"] = "generated"
    selected: bool = False
    important: bool = False
    importance: float | None = None
    shap: float | None = None
    modelIds: list[str] = Field(default_factory=list)
    featureType: Literal["generated", "known_future_covariate", "static_covariate", "unknown_future_covariate"] = "generated"
    generator: str = "Feature Factory"
    machineId: str | None = None
    machineLabel: str | None = None
    forecastStrategy: Literal["generated", "calendar", "use_future_rows", "repeat_last_known", "use_test_timeline", "forecast_auxiliary", "drop_for_leakage"] = "generated"
    backtestStrategy: Literal["generated", "calendar", "use_future_rows", "repeat_last_known", "use_test_timeline", "forecast_auxiliary", "drop_for_leakage"] = "generated"
    usedDuring: list[Literal["training", "backtest", "forecast"]] = Field(default_factory=lambda: ["training"])
    droppedReason: str | None = None
    lifecycleTrail: list[str] = Field(default_factory=list)


class RuntimeFeatureFactorySummary(BaseModel):
    rawColumnCount: int = 0
    generatedFeatureCount: int = 0
    userCovariateCount: int = 0
    selectedFeatureCount: int = 0
    droppedFeatureCount: int = 0
    importantFeatureCount: int = 0
    shapSupportedFeatureCount: int = 0


class RuntimeFeatureMachine(BaseModel):
    id: str
    label: str
    kind: Literal["generator", "loader"] = "generator"
    enabled: bool = True
    status: FeatureStepStatus = "completed"
    inputColumns: list[str] = Field(default_factory=list)
    generatedFeatures: list[str] = Field(default_factory=list)
    summary: str = ""
    durationSeconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class RuntimeCovariateDescriptor(BaseModel):
    name: str
    type: Literal["known_future", "static", "unknown_future"]
    generator: str = "Covariate Loader"
    forecastStrategy: Literal["calendar", "use_future_rows", "repeat_last_known", "forecast_auxiliary", "drop_for_leakage"]
    backtestStrategy: Literal["use_test_timeline", "repeat_last_known", "forecast_auxiliary", "drop_for_leakage"]
    usedDuring: list[Literal["training", "backtest", "forecast"]] = Field(default_factory=lambda: ["training", "backtest", "forecast"])
    forecastMode: Literal["auto", "manual", "per_primary_model"] | None = None
    forecastModelId: str | None = None
    note: str | None = None


class RuntimeFeatureSelectionItem(BaseModel):
    name: str
    status: Literal["selected", "dropped"]
    reason: str | None = None


class RuntimeFeatureSelectionSummary(BaseModel):
    generatedCount: int = 0
    selectedCount: int = 0
    droppedCount: int = 0
    items: list[RuntimeFeatureSelectionItem] = Field(default_factory=list)


class RuntimeFeatureColumnProfile(BaseModel):
    name: str
    dtype: str = "float64"
    nonNullCount: int = 0
    nullCount: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    std: float | None = None


class RuntimeFeatureDataProfile(BaseModel):
    rowCount: int = 0
    columnCount: int = 0
    columns: list[str] = Field(default_factory=list)
    missingValueCount: int = 0
    invalidValueCount: int = 0
    memoryBytes: int = 0
    columnProfiles: list[RuntimeFeatureColumnProfile] = Field(default_factory=list)


class RuntimeFeatureVisualizationMarker(BaseModel):
    time: str
    label: str
    kind: str = "event"


class RuntimeFeatureVisualization(BaseModel):
    kind: str
    timeStart: str | None = None
    timeEnd: str | None = None
    markers: list[RuntimeFeatureVisualizationMarker] = Field(default_factory=list)
    sampleValues: list[float] = Field(default_factory=list)
    sampleLabels: list[str] = Field(default_factory=list)
    windowSize: int | None = None


class RuntimeFeaturePipelineStep(BaseModel):
    id: str
    sequence: int = 0
    label: str
    description: str = ""
    machineId: str | None = None
    status: FeatureStepStatus = "pending"
    progressPercent: int = Field(default=0, ge=0, le=100)
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    inputSummary: str = ""
    outputSummary: str = ""
    inputProfile: RuntimeFeatureDataProfile | None = None
    outputProfile: RuntimeFeatureDataProfile | None = None
    generatedFeatures: list[str] = Field(default_factory=list)
    selectedFeatures: list[str] = Field(default_factory=list)
    droppedFeatures: list[str] = Field(default_factory=list)
    skipReason: str | None = None
    error: str | None = None
    elapsedSeconds: float | None = None
    warnings: list[str] = Field(default_factory=list)
    visualization: RuntimeFeatureVisualization | None = None


class RuntimeFeaturePipelineTarget(BaseModel):
    schemaVersion: Literal["0.4"] = "0.4"
    targetColumn: str
    detectedFrequency: str | None = None
    status: FeatureStepStatus = "pending"
    progressPercent: int = Field(default=0, ge=0, le=100)
    currentStepId: str | None = None
    traceMode: Literal["live", "reconstructed", "legacy_inferred"] = "live"
    warnings: list[str] = Field(default_factory=list)
    families: list[RuntimeFeatureFamily] = Field(default_factory=list)
    steps: list[RuntimeFeaturePipelineStep] = Field(default_factory=list)
    lineage: list[RuntimeFeatureNode] = Field(default_factory=list)
    summary: RuntimeFeatureFactorySummary | None = None
    machines: list[RuntimeFeatureMachine] = Field(default_factory=list)
    covariates: list[RuntimeCovariateDescriptor] = Field(default_factory=list)
    selection: RuntimeFeatureSelectionSummary | None = None


class RuntimeOptimizationTrial(BaseModel):
    trialNumber: int
    params: dict[str, Any] = Field(default_factory=dict)
    status: Literal["running", "success", "failed", "pruned"] = "success"
    metric: float | None = None
    metricLabel: str = "MAE"
    elapsedSeconds: float = 0.0
    selected: bool = False
    message: str | None = None


class RuntimeOptimizationState(BaseModel):
    modelId: str
    modelName: str
    targetColumn: str
    enabled: bool = False
    strategyLabel: str = "Default Parameters"
    sampler: str | None = None
    pruner: str | None = None
    currentTrial: int = 0
    totalTrials: int = 0
    bestMetric: float | None = None
    currentMetric: float | None = None
    metricLabel: str = "MAE"
    selectedParams: dict[str, Any] = Field(default_factory=dict)
    status: Literal["idle", "running", "completed", "failed"] = "idle"
    lastMessage: str | None = None
    trials: list[RuntimeOptimizationTrial] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimeModelConsole(BaseModel):
    modelId: str
    modelName: str
    targetColumn: str
    status: Literal["queued", "tuning", "fitting", "predicting", "scoring", "success", "failed"] = "queued"
    currentStage: RuntimeStageId = "pending"
    progressPercent: int = Field(default=0, ge=0, le=100)
    message: str = "Waiting to run."
    elapsedSeconds: float = 0.0
    estimatedSeconds: float | None = None
    estimatedRemainingSeconds: float | None = None
    fitSeconds: float | None = None
    predictSeconds: float | None = None
    tuningSeconds: float | None = None
    computeTarget: Literal["cpu", "gpu"] = "cpu"
    resource: RuntimeResourceSnapshot | None = None
    optimization: RuntimeOptimizationState | None = None
    error: str | None = None


class RuntimeRunDetail(BaseModel):
    runId: str
    experimentId: str | None = None
    kind: Literal["backtest", "final"]
    status: Literal["running", "completed", "failed"] = "running"
    currentStage: RuntimeStageId = "pending"
    currentStageLabel: str = "Pending"
    overallPercent: int = Field(default=0, ge=0, le=100)
    message: str = ""
    currentTarget: str | None = None
    estimatedTotalSeconds: float | None = None
    estimatedRemainingSeconds: float | None = None
    elapsedSeconds: float = 0.0
    startedAt: datetime
    updatedAt: datetime
    stateMachine: list[RuntimeStateStep] = Field(default_factory=list)
    resources: RuntimeResourceSnapshot | None = None
    models: list[RuntimeModelConsole] = Field(default_factory=list)
    logs: list[RuntimeLogEntry] = Field(default_factory=list)
    timeline: list[RuntimeTimelineEntry] = Field(default_factory=list)
    events: list[RuntimeEvent] = Field(default_factory=list)
    featurePipeline: list[RuntimeFeaturePipelineTarget] = Field(default_factory=list)
    optimization: list[RuntimeOptimizationState] = Field(default_factory=list)
    error: str | None = None


class RuntimeLogsResponse(BaseModel):
    runId: str
    logs: list[RuntimeLogEntry] = Field(default_factory=list)


class RuntimeEventsResponse(BaseModel):
    runId: str
    events: list[RuntimeEvent] = Field(default_factory=list)


class RuntimeFeaturePipelineResponse(BaseModel):
    runId: str
    targets: list[RuntimeFeaturePipelineTarget] = Field(default_factory=list)


class FeatureFactoryResponse(BaseModel):
    experimentId: str
    targets: list[RuntimeFeaturePipelineTarget] = Field(default_factory=list)


class RuntimeOptimizationResponse(BaseModel):
    runId: str
    models: list[RuntimeOptimizationState] = Field(default_factory=list)


class RuntimeTimelineResponse(BaseModel):
    runId: str
    timeline: list[RuntimeTimelineEntry] = Field(default_factory=list)


class RuntimeEstimateItem(BaseModel):
    id: str
    name: str
    estimatedSeconds: float = Field(ge=0)
    confidence: Literal["low", "medium", "high"] = "low"
    reason: str
    sampleCount: int = Field(default=0, ge=0)
    computeTarget: Literal["cpu", "gpu"] = "cpu"


class RuntimeEstimateResponse(BaseModel):
    models: list[RuntimeEstimateItem]


class ExperimentListItem(BaseModel):
    experimentId: str
    experimentName: str
    fileName: str
    sheetName: str
    targetColumn: str
    modelCount: int
    recommendedModelId: str | None
    bestMae: float | None
    createdAt: str


class ExperimentDetail(BaseModel):
    experimentId: str
    experimentName: str
    fileName: str
    sheetName: str
    targetColumn: str
    recommendedModelId: str | None
    bestMae: float | None
    createdAt: str
    config: dict[str, Any]
    dataProfile: dict[str, Any]
    rankedModels: list[dict[str, Any]]
    backtest: dict[str, Any]
    diagnostics: dict[str, Any]
    dataHealth: dict[str, Any] | None = None
    series: list[dict[str, Any]]
    finalForecast: dict[str, Any] | None
    modelLogs: list[dict[str, Any]]
    runtime: RuntimeRunDetail | None = None
    manifest: dict[str, Any] | None = None
    configHash: str | None = None
    sourceFileSha256: str | None = None
    appVersion: str | None = None
    gitCommit: str | None = None
    reports: list[dict[str, Any]] = Field(default_factory=list)


class ManifestEnvironment(BaseModel):
    appVersion: str
    gitCommit: str | None = None
    pythonVersion: str
    platform: str
    device: str
    memoryTotalMb: int | None = None
    memoryAvailableMb: int | None = None
    modelCapabilityVersions: dict[str, Any] | None = None
    packageVersions: dict[str, str] = Field(default_factory=dict)


class ManifestDataSnapshot(BaseModel):
    fileName: str
    fileSize: int
    fileSha256: str
    sheetName: str
    columns: list[str]
    timeColumn: str
    targetColumns: list[str]
    covariateColumns: list[str] = Field(default_factory=list)


class ManifestModelResult(BaseModel):
    modelId: str
    modelName: str
    status: Literal["success", "failed"]
    metrics: dict[str, Any] | None = None
    runtime: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    tuning: dict[str, Any] | None = None


class ManifestTargetSnapshot(BaseModel):
    targetColumn: str
    detectedFrequency: str
    timeStart: str | None = None
    timeEnd: str | None = None
    trainStart: str | None = None
    trainEnd: str | None = None
    testStart: str | None = None
    testEnd: str | None = None
    recommendedModelId: str | None = None
    models: list[ManifestModelResult] = Field(default_factory=list)


class ExperimentManifest(BaseModel):
    schemaVersion: Literal["0.3", "0.4"] = "0.4"
    experimentId: str
    experimentName: str
    createdAt: str | None = None
    configHash: str
    sourceFileSha256: str
    datasetHash: str | None = None
    featurePipelineVersion: str | None = None
    runtimeEventSchemaVersion: str | None = None
    randomSeed: int | None = None
    environment: ManifestEnvironment
    data: ManifestDataSnapshot
    configuration: dict[str, Any]
    targets: list[ManifestTargetSnapshot] = Field(default_factory=list)
    featurePipelines: list[RuntimeFeaturePipelineTarget] = Field(default_factory=list)


class ExperimentRerunFileMatch(BaseModel):
    uploadId: str | None = None
    uploadedFileName: str | None = None
    uploadedFileSha256: str | None = None
    fileNameMatches: bool | None = None
    sha256Matches: bool | None = None
    exactMatch: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class ExperimentRerunRequest(BaseModel):
    experimentId: str
    uploadId: str | None = None


class ExperimentRerunResponse(BaseModel):
    experimentId: str
    configHash: str
    sourceFileSha256: str
    manifest: ExperimentManifest
    runRequestTemplate: dict[str, Any]
    fileMatch: ExperimentRerunFileMatch


WorkbenchAgentMode = Literal["offline", "online", "dual"]
WorkbenchIdeaRoute = Literal["feature_engineering_data", "custom_model", "hybrid", "clarify", "unsupported"]


class WorkbenchIdeaContext(BaseModel):
    targetColumn: str | None = None
    frequency: str | None = None
    availableColumns: list[str] = Field(default_factory=list)
    horizon: int | None = None
    domain: str | None = None


class WorkbenchIdeaAnalyzeRequest(BaseModel):
    idea: str = Field(min_length=1)
    context: WorkbenchIdeaContext = Field(default_factory=WorkbenchIdeaContext)
    mode: WorkbenchAgentMode = "offline"


class WorkbenchDataSourceCandidate(BaseModel):
    id: str
    name: str
    category: Literal["built_in", "user_upload", "external_registry", "connector_placeholder"]
    description: str
    frequencySupport: list[str] = Field(default_factory=list)
    futureAvailability: Literal["known_future", "static", "unknown_future", "not_applicable"] = "not_applicable"
    implementationStatus: Literal["available", "placeholder", "unsupported"] = "available"
    warnings: list[str] = Field(default_factory=list)


class WorkbenchDataSearchPlan(BaseModel):
    query: str
    intent: str
    requiredFields: list[str] = Field(default_factory=list)
    suggestedJoinKeys: list[str] = Field(default_factory=list)
    candidateApiCalls: list[str] = Field(default_factory=list)


class WorkbenchCovariatePlan(BaseModel):
    suggestedColumns: list[str] = Field(default_factory=list)
    covariateType: Literal["known_future", "static", "unknown_future", "mixed", "none"] = "none"
    backtestPolicy: str = ""
    forecastPolicy: str = ""
    leakagePolicy: str = ""


class WorkbenchCustomModelSpec(BaseModel):
    modelId: str | None = None
    displayName: str | None = None
    objective: str | None = None
    requiredInputs: list[str] = Field(default_factory=list)
    trainingStrategy: str | None = None
    predictionInterface: str | None = None
    safetyNotes: list[str] = Field(default_factory=list)
    executableCodeAllowed: bool = False


class WorkbenchOnlineObservation(BaseModel):
    attempted: bool = False
    status: Literal["not_configured", "skipped", "success", "failed"] = "skipped"
    message: str = ""
    route: WorkbenchIdeaRoute | None = None
    confidence: float | None = None


class WorkbenchIdeaAnalyzeResponse(BaseModel):
    route: WorkbenchIdeaRoute
    confidence: float = Field(ge=0, le=1)
    rationale: str
    requiredInputs: list[str] = Field(default_factory=list)
    dataSearchPlan: WorkbenchDataSearchPlan | None = None
    candidateDataSources: list[WorkbenchDataSourceCandidate] = Field(default_factory=list)
    covariatePlan: WorkbenchCovariatePlan | None = None
    customModelSpec: WorkbenchCustomModelSpec | None = None
    leakageWarnings: list[str] = Field(default_factory=list)
    nextApiCalls: list[str] = Field(default_factory=list)
    onlineObservation: WorkbenchOnlineObservation | None = None


class WorkbenchDataSourceSearchRequest(BaseModel):
    query: str = ""
    domain: str | None = None
    frequency: str | None = None
    route: WorkbenchIdeaRoute | None = None


class WorkbenchDataSourceSearchResponse(BaseModel):
    query: str
    candidates: list[WorkbenchDataSourceCandidate] = Field(default_factory=list)


class WorkbenchCustomModelSpecRequest(BaseModel):
    idea: str = Field(min_length=1)
    context: WorkbenchIdeaContext = Field(default_factory=WorkbenchIdeaContext)


class WorkbenchCustomModelValidateRequest(BaseModel):
    spec: WorkbenchCustomModelSpec


class WorkbenchCustomModelValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    normalizedSpec: WorkbenchCustomModelSpec


class DeepSeekConnectionRequest(BaseModel):
    apiKey: str = Field(min_length=1)
    baseUrl: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"


class DeepSeekConnectionResponse(BaseModel):
    success: bool
    model: str
    message: str
    code: str | None = None


class LocalRebuildRequest(BaseModel):
    password: str = Field(min_length=1)
    delaySeconds: int = Field(default=2, ge=0, le=30)


class LocalRebuildResponse(BaseModel):
    accepted: bool
    message: str
    scriptPath: str
    logPath: str | None = None


class ReportOptions(BaseModel):
    language: str = "zh-CN"
    style: Literal["business", "technical"] = "business"
    length: Literal["short", "medium", "long"] = "medium"
    includeFeaturePipeline: bool = True
    includeWorkflowReport: bool = True
    includeModelRecommendation: bool = True
    includeModelComparison: bool = True
    includeResidualAnalysis: bool = True
    includeFinalForecast: bool = True
    includeWarnings: bool = True


class GenerateReportRequest(BaseModel):
    experimentId: str
    apiKey: str = Field(min_length=1)
    baseUrl: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    reportOptions: ReportOptions = Field(default_factory=ReportOptions)


class ReportResponse(BaseModel):
    reportId: str
    experimentId: str
    contentMarkdown: str
    createdAt: str
    model: str


class ReportPdfArtifact(BaseModel):
    id: str
    title: str
    caption: str
    dataUrl: str
    summary: list[str] = Field(default_factory=list)


class GenerateReportPdfRequest(BaseModel):
    title: str | None = None
    visualArtifacts: list[ReportPdfArtifact] = Field(default_factory=list)


FeedbackKind = Literal["urgent", "feedback", "ramble"]
FeedbackStatus = Literal["open", "in_progress", "done", "ignored"]
FeedbackNotifyStatus = Literal["pending", "sent", "failed", "skipped"]


class FeedbackCreateRequest(BaseModel):
    kind: FeedbackKind = "feedback"
    title: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1, max_length=8000)
    sourcePage: str | None = Field(default=None, max_length=512)


class FeedbackItem(BaseModel):
    feedbackId: str
    kind: FeedbackKind
    title: str | None = None
    content: str
    sourcePage: str | None = None
    status: FeedbackStatus
    notifyStatus: FeedbackNotifyStatus
    notifyError: str | None = None
    createdAt: str
    updatedAt: str


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItem]


class FeedbackStatusUpdateRequest(BaseModel):
    status: FeedbackStatus


class FeedbackNotifyTestRequest(BaseModel):
    message: str = Field(default="企业微信反馈通知测试", min_length=1, max_length=1000)


class FeedbackNotifyTestResponse(BaseModel):
    success: bool
    notifyStatus: FeedbackNotifyStatus
    message: str
    error: str | None = None
