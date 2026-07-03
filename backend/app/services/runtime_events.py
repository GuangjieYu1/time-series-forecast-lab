from __future__ import annotations

from datetime import datetime, timezone
from threading import active_count
from uuid import uuid4

from app.core.gpu import get_memory_info
from app.schemas import RuntimeLogEntry, RuntimeResourceSnapshot, RuntimeStageId, RuntimeTimelineEntry
from app.services.runtime_state_machine import stage_label


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_resource_snapshot(device: str) -> RuntimeResourceSnapshot:
    memory = get_memory_info()
    total_mb = memory.get("memoryTotalMb")
    available_mb = memory.get("memoryAvailableMb")
    used_mb = None
    if total_mb is not None and available_mb is not None:
        used_mb = round(max(float(total_mb - available_mb), 0.0), 2)
    gpu_label = None
    lowered = str(device or "cpu").lower()
    if "cuda" in lowered or "gpu" in lowered:
        gpu_label = "GPU"
    elif "mps" in lowered:
        gpu_label = "Apple Silicon GPU"
    return RuntimeResourceSnapshot(
        device=device,
        memoryTotalMb=total_mb,
        memoryAvailableMb=available_mb,
        memoryUsedMb=used_mb,
        cpuPercent=None,
        threadCount=active_count(),
        gpuLabel=gpu_label,
    )


def make_log_entry(
    *,
    stage: RuntimeStageId,
    message: str,
    level: str = "info",
    timestamp: datetime | None = None,
    model_id: str | None = None,
    model_name: str | None = None,
    target_column: str | None = None,
    metric_label: str | None = None,
    metric_value: float | None = None,
    params: dict | None = None,
) -> RuntimeLogEntry:
    return RuntimeLogEntry(
        id=f"log_{uuid4().hex[:12]}",
        timestamp=timestamp or utc_now(),
        stage=stage,
        level=level,
        message=message,
        modelId=model_id,
        modelName=model_name,
        targetColumn=target_column,
        metricLabel=metric_label,
        metricValue=metric_value,
        params=params or {},
    )


def make_timeline_entry(
    *,
    stage: RuntimeStageId,
    status: str,
    message: str | None = None,
    timestamp: datetime | None = None,
    model_id: str | None = None,
    model_name: str | None = None,
    target_column: str | None = None,
    overall_percent: int | None = None,
) -> RuntimeTimelineEntry:
    return RuntimeTimelineEntry(
        id=f"timeline_{uuid4().hex[:12]}",
        timestamp=timestamp or utc_now(),
        stage=stage,
        label=stage_label(stage),
        status=status,
        message=message,
        modelId=model_id,
        modelName=model_name,
        targetColumn=target_column,
        overallPercent=overall_percent,
    )


def elapsed_seconds(started_at: datetime, now: datetime | None = None) -> float:
    current = now or utc_now()
    return round(max((current - started_at).total_seconds(), 0.0), 4)
