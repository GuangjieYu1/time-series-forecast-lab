from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class ForecastRunRequest(BaseModel):
    runId: str | None = None
    uploadId: str
    sheetName: str
    dataMode: Literal["aggregated", "raw"]
    timeColumn: str
    targetColumns: list[str]
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    frequency: str = "auto"
    horizon: int = Field(ge=1)
    testSize: int = Field(ge=1)
    selectedModels: list[str]
    missingValueStrategy: Literal["drop", "zero", "ffill", "interpolate"] = "drop"
    fillMissingTimeSteps: bool = True
    duplicateTimeStrategy: Literal["mean", "sum", "first", "last"] = "mean"
    outlierStrategy: Literal["none", "clip_iqr"] = "none"
    outlierIqrMultiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    trimStrings: bool = True
    experimentName: str | None = None


class MetricValues(BaseModel):
    mae: float | None = None
    mse: float | None = None
    rmse: float | None = None
    wape: float | None = None


class ModelRuntime(BaseModel):
    fitSeconds: float = 0.0
    predictSeconds: float = 0.0


class RankedModel(BaseModel):
    modelId: str
    modelName: str
    rank: int | None = None
    metrics: MetricValues | None = None
    runtime: ModelRuntime
    status: Literal["success", "failed"] = "success"
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


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


class TargetResult(BaseModel):
    targetColumn: str
    detectedFrequency: str
    recommendedModelId: str | None
    rankedModels: list[RankedModel]
    backtest: BacktestData
    diagnostics: Diagnostics


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
    targetResults: list[TargetResult]


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
    status: Literal["queued", "fitting", "predicting", "scoring", "success", "failed"] = "queued"
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
    series: list[dict[str, Any]]
    finalForecast: dict[str, Any] | None
    modelLogs: list[dict[str, Any]]
    reports: list[dict[str, Any]] = Field(default_factory=list)


class DeepSeekConnectionRequest(BaseModel):
    apiKey: str = Field(min_length=1)
    baseUrl: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"


class DeepSeekConnectionResponse(BaseModel):
    success: bool
    model: str
    message: str
    code: str | None = None


class ReportOptions(BaseModel):
    language: str = "zh-CN"
    style: Literal["business", "technical"] = "business"
    length: Literal["short", "medium", "long"] = "medium"
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
