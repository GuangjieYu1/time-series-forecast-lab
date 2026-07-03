from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    covariates: bool = True


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
    missingValueStrategy: Literal["drop", "zero", "ffill", "interpolate"] = "drop"
    fillMissingTimeSteps: bool = True
    duplicateTimeStrategy: Literal["mean", "sum", "first", "last"] = "mean"
    outlierStrategy: Literal["none", "clip_iqr"] = "none"
    outlierIqrMultiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    trimStrings: bool = True
    runProfile: Literal["fast", "balanced", "accurate"] = "balanced"
    parameterStrategy: Literal["default", "auto"] = "default"
    randomSeed: int = DEFAULT_RANDOM_SEED
    experimentName: str | None = None


class RuntimeEstimateRequest(BaseModel):
    rowCount: int = Field(ge=1)
    frequency: str = "auto"
    totalColumnCount: int = Field(default=1, ge=1)
    targetCount: int = Field(default=1, ge=1)
    covariateCount: int = Field(default=0, ge=0)
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
    message: str | None = None
    modelId: str | None = None
    modelName: str | None = None
    targetColumn: str | None = None
    overallPercent: int | None = None


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
    featureType: Literal["generated", "known_future_covariate", "static_covariate"] = "generated"
    generator: str = "Feature Factory"
    machineId: str | None = None
    machineLabel: str | None = None
    forecastStrategy: Literal["generated", "calendar", "repeat_last_known", "use_test_timeline"] = "generated"
    backtestStrategy: Literal["generated", "calendar", "repeat_last_known", "use_test_timeline"] = "generated"
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
    status: RuntimeStepStatus = "completed"
    inputColumns: list[str] = Field(default_factory=list)
    generatedFeatures: list[str] = Field(default_factory=list)
    summary: str = ""
    durationSeconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class RuntimeCovariateDescriptor(BaseModel):
    name: str
    type: Literal["known_future", "static"]
    generator: str = "Covariate Loader"
    forecastStrategy: Literal["calendar", "repeat_last_known"]
    backtestStrategy: Literal["use_test_timeline", "repeat_last_known"]
    usedDuring: list[Literal["training", "backtest", "forecast"]] = Field(default_factory=lambda: ["training", "backtest", "forecast"])
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


class RuntimeFeaturePipelineStep(BaseModel):
    id: RuntimeStageId
    label: str
    status: RuntimeStepStatus = "pending"
    inputSummary: str = ""
    outputSummary: str = ""
    elapsedSeconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class RuntimeFeaturePipelineTarget(BaseModel):
    targetColumn: str
    detectedFrequency: str | None = None
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
    featurePipeline: list[RuntimeFeaturePipelineTarget] = Field(default_factory=list)
    optimization: list[RuntimeOptimizationState] = Field(default_factory=list)
    error: str | None = None


class RuntimeLogsResponse(BaseModel):
    runId: str
    logs: list[RuntimeLogEntry] = Field(default_factory=list)


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
    schemaVersion: Literal["0.3"] = "0.3"
    experimentId: str
    experimentName: str
    createdAt: str | None = None
    configHash: str
    sourceFileSha256: str
    environment: ManifestEnvironment
    data: ManifestDataSnapshot
    configuration: dict[str, Any]
    targets: list[ManifestTargetSnapshot] = Field(default_factory=list)


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
