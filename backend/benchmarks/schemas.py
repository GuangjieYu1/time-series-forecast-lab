from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchmarkModelResult(BaseModel):
    modelId: str
    modelName: str | None = None
    status: Literal["success", "failed"]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    metrics: dict[str, Any] | None = None


class BenchmarkCaseResult(BaseModel):
    name: str
    category: Literal["clean", "dirty", "edge", "large"]
    fileFormat: str
    rowCount: int | None = None
    columnCount: int | None = None
    targetColumns: list[str] = Field(default_factory=list)
    covariateColumns: list[str] = Field(default_factory=list)
    selectedModels: list[str] = Field(default_factory=list)
    uploadStatus: str
    runStatus: str
    seconds: float = Field(ge=0)
    memoryMb: float = Field(ge=0)
    warningCount: int = Field(ge=0)
    bestMae: float | None = None
    dataHealthScore: float | None = None
    modelStatuses: dict[str, str] = Field(default_factory=dict)
    modelResults: list[BenchmarkModelResult] = Field(default_factory=list)
    experimentId: str | None = None
    error: str | None = None


class BenchmarkSummary(BaseModel):
    schemaVersion: Literal["0.4"] = "0.4"
    profile: Literal["fast", "balanced", "accurate"]
    generatedAt: str
    seconds: float = Field(ge=0)
    totalCases: int = Field(ge=0)
    successfulRuns: int = Field(ge=0)
    failedRuns: int = Field(ge=0)
    successRate: float = Field(ge=0, le=1)
    failureRate: float = Field(ge=0, le=1)
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)
