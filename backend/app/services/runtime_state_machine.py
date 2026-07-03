from __future__ import annotations

from datetime import datetime

from app.schemas import RuntimeStageId, RuntimeStateStep


RUNTIME_STAGE_SEQUENCE: list[tuple[RuntimeStageId, str]] = [
    ("pending", "Pending"),
    ("loading", "Loading"),
    ("cleaning", "Cleaning"),
    ("feature_engineering", "Feature Engineering"),
    ("feature_selection", "Feature Selection"),
    ("auto_tuning", "Auto Tuning"),
    ("training", "Training"),
    ("forecast", "Forecast"),
    ("residual_analysis", "Residual Analysis"),
    ("finished", "Finished"),
]

RUNTIME_STAGE_LABELS = {stage_id: label for stage_id, label in RUNTIME_STAGE_SEQUENCE} | {"failed": "Failed"}
RUNTIME_STAGE_ORDER = {stage_id: index for index, (stage_id, _label) in enumerate(RUNTIME_STAGE_SEQUENCE)}


def stage_label(stage: RuntimeStageId) -> str:
    return RUNTIME_STAGE_LABELS.get(stage, "Pending")


def build_state_machine(now: datetime | None = None) -> list[RuntimeStateStep]:
    timestamp = now
    steps: list[RuntimeStateStep] = []
    for index, (stage_id, label) in enumerate(RUNTIME_STAGE_SEQUENCE):
        status = "running" if index == 0 else "pending"
        started_at = timestamp if index == 0 else None
        steps.append(RuntimeStateStep(id=stage_id, label=label, status=status, startedAt=started_at))
    return steps


def transition_state_machine(
    current_steps: list[RuntimeStateStep],
    *,
    stage: RuntimeStageId,
    now: datetime,
    terminal_status: str = "running",
) -> list[RuntimeStateStep]:
    steps = [step.model_copy(deep=True) for step in current_steps] or build_state_machine(now)
    stage_index = RUNTIME_STAGE_ORDER.get(stage, 0)

    for index, step in enumerate(steps):
        if terminal_status == "failed":
            if index < stage_index:
                _mark_completed(step, now)
            elif index == stage_index:
                _mark_failed(step, now)
            else:
                step.status = "pending"
        elif terminal_status == "completed" and stage == "finished":
            if index < stage_index:
                _mark_completed(step, now)
            elif index == stage_index:
                _mark_completed(step, now)
            else:
                step.status = "pending"
        else:
            if index < stage_index:
                _mark_completed(step, now)
            elif index == stage_index:
                _mark_running(step, now)
            else:
                step.status = "pending"
        _refresh_elapsed(step, now)
    return steps


def stage_from_phase(phase: str) -> RuntimeStageId:
    if phase in {"preparing"}:
        return "pending"
    if phase in {"parsing"}:
        return "loading"
    if phase in {"profiling"}:
        return "cleaning"
    if phase in {"building_series"}:
        return "feature_engineering"
    if phase in {"model_tuning"}:
        return "auto_tuning"
    if phase in {"model_fitting", "fitting"}:
        return "training"
    if phase in {"model_predicting", "predicting"}:
        return "forecast"
    if phase in {"model_scoring", "ranking"}:
        return "residual_analysis"
    if phase in {"saving", "completed"}:
        return "finished"
    if phase in {"failed"}:
        return "failed"
    return "pending"


def _mark_running(step: RuntimeStateStep, now: datetime) -> None:
    if step.startedAt is None:
        step.startedAt = now
    if step.id == "finished":
        step.status = "completed"
        if step.finishedAt is None:
            step.finishedAt = now
        return
    step.status = "running"
    step.finishedAt = None


def _mark_completed(step: RuntimeStateStep, now: datetime) -> None:
    if step.startedAt is None:
        step.startedAt = now
    step.status = "completed"
    if step.finishedAt is None:
        step.finishedAt = now


def _mark_failed(step: RuntimeStateStep, now: datetime) -> None:
    if step.startedAt is None:
        step.startedAt = now
    step.status = "failed"
    step.finishedAt = now


def _refresh_elapsed(step: RuntimeStateStep, now: datetime) -> None:
    if step.startedAt is None:
        step.elapsedSeconds = None
        return
    end = step.finishedAt or now
    step.elapsedSeconds = round(max((end - step.startedAt).total_seconds(), 0.0), 4)
