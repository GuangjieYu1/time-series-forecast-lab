from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AssertionStatus = Literal["passed", "failed", "warning", "skipped"]


class BenchmarkAssertion(BaseModel):
    name: str
    status: AssertionStatus
    message: str = ""
    expected: Any | None = None
    actual: Any | None = None
    tolerance: float | None = None


class BenchmarkModelResult(BaseModel):
    modelId: str
    modelName: str | None = None
    status: Literal["success", "failed"]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    metrics: dict[str, Any] | None = None


class AggregationBenchmarkResult(BaseModel):
    method: str
    maxAbsDiff: float | None = None
    comparedPoints: int = 0
    expectedSeriesHash: str | None = None
    actualSeriesHash: str | None = None


class FeatureLiftBenchmarkResult(BaseModel):
    modelId: str | None = None
    baselineMae: float | None = None
    featureMae: float | None = None
    improvementRatio: float | None = None
    noiseDegradationRatio: float | None = None
    leakageProtected: bool | None = None


class ReproducibilityBenchmarkResult(BaseModel):
    reproducibilityScore: float = Field(default=0, ge=0, le=1)
    driftItems: list[str] = Field(default_factory=list)
    ignoredVolatileFields: list[str] = Field(default_factory=list)
    firstExperimentId: str | None = None
    secondExperimentId: str | None = None


class AgentRoutingBenchmarkResult(BaseModel):
    routeAccuracy: float = Field(default=0, ge=0, le=1)
    schemaValidity: float = Field(default=0, ge=0, le=1)
    leakageWarningRecall: float = Field(default=0, ge=0, le=1)
    unsupportedPromiseCount: int = Field(default=0, ge=0)
    onlineWarnings: list[str] = Field(default_factory=list)


class BenchmarkCaseResult(BaseModel):
    name: str
    suite: str = "stability"
    category: str
    fileFormat: str = "-"
    rowCount: int | None = None
    columnCount: int | None = None
    targetColumns: list[str] = Field(default_factory=list)
    covariateColumns: list[str] = Field(default_factory=list)
    selectedModels: list[str] = Field(default_factory=list)
    uploadStatus: str = "skipped"
    runStatus: str = "skipped"
    seconds: float = Field(ge=0)
    memoryMb: float = Field(ge=0)
    warningCount: int = Field(ge=0)
    bestMae: float | None = None
    dataHealthScore: float | None = None
    modelStatuses: dict[str, str] = Field(default_factory=dict)
    modelResults: list[BenchmarkModelResult] = Field(default_factory=list)
    experimentId: str | None = None
    error: str | None = None
    passed: bool = True
    assertions: list[BenchmarkAssertion] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    aggregationResult: AggregationBenchmarkResult | None = None
    featureLiftResult: FeatureLiftBenchmarkResult | None = None
    reproducibilityResult: ReproducibilityBenchmarkResult | None = None
    agentRoutingResult: AgentRoutingBenchmarkResult | None = None


class BenchmarkSummary(BaseModel):
    schemaVersion: Literal["0.5"] = "0.5"
    profile: Literal["fast", "balanced", "accurate"]
    suite: str = "all"
    agentMode: Literal["offline", "online", "dual"] = "offline"
    generatedAt: str
    seconds: float = Field(ge=0)
    totalCases: int = Field(ge=0)
    successfulRuns: int = Field(ge=0)
    failedRuns: int = Field(ge=0)
    successRate: float = Field(ge=0, le=1)
    failureRate: float = Field(ge=0, le=1)
    failedAssertions: int = Field(default=0, ge=0)
    warningAssertions: int = Field(default=0, ge=0)
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)
