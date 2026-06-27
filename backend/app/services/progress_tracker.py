from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Literal

from app.schemas import ForecastProgress, ModelProgress


TerminalStatus = Literal["completed", "failed"]


class ProgressTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, ForecastProgress] = {}
        self._versions: dict[str, int] = {}
        self._history: dict[str, list[ForecastProgress]] = {}

    def start(
        self,
        run_id: str,
        kind: Literal["backtest", "final"],
        model_rows: list[ModelProgress],
        message: str,
    ) -> ForecastProgress:
        now = datetime.now(timezone.utc)
        snapshot = ForecastProgress(
            runId=run_id,
            kind=kind,
            status="running",
            phase="preparing",
            overallPercent=1,
            message=message,
            completedModels=0,
            totalModels=len(model_rows),
            models=model_rows,
            startedAt=now,
            updatedAt=now,
            version=1,
        )
        with self._lock:
            self._cleanup_locked(now)
            self._runs[run_id] = snapshot
            self._versions[run_id] = 1
            self._history[run_id] = [snapshot.model_copy(deep=True)]
            return snapshot.model_copy(deep=True)

    def update(self, run_id: str, **changes) -> ForecastProgress | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return None
            version = self._versions.get(run_id, current.version) + 1
            changes["updatedAt"] = datetime.now(timezone.utc)
            changes["version"] = version
            updated = current.model_copy(update=changes, deep=True)
            self._runs[run_id] = updated
            self._versions[run_id] = version
            self._history.setdefault(run_id, []).append(updated.model_copy(deep=True))
            return updated.model_copy(deep=True)

    def update_model(
        self,
        run_id: str,
        target_column: str,
        model_id: str,
        **changes,
    ) -> ForecastProgress | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return None
            rows = deepcopy(current.models)
            for index, row in enumerate(rows):
                if row.targetColumn == target_column and row.modelId == model_id:
                    rows[index] = row.model_copy(update=changes, deep=True)
                    break
            version = self._versions.get(run_id, current.version) + 1
            completed = sum(row.status in {"success", "failed"} for row in rows)
            updated = current.model_copy(
                update={
                    "models": rows,
                    "completedModels": completed,
                    "updatedAt": datetime.now(timezone.utc),
                    "version": version,
                },
                deep=True,
            )
            self._runs[run_id] = updated
            self._versions[run_id] = version
            self._history.setdefault(run_id, []).append(updated.model_copy(deep=True))
            return updated.model_copy(deep=True)

    def finish(self, run_id: str, status: TerminalStatus, message: str, error: str | None = None) -> ForecastProgress | None:
        return self.update(
            run_id,
            status=status,
            phase=status,
            overallPercent=100 if status == "completed" else 100,
            message=message,
            error=error,
        )

    def get(self, run_id: str) -> ForecastProgress | None:
        with self._lock:
            current = self._runs.get(run_id)
            return current.model_copy(deep=True) if current else None

    def get_after(self, run_id: str, version: int) -> list[ForecastProgress]:
        with self._lock:
            return [
                item.model_copy(deep=True)
                for item in self._history.get(run_id, [])
                if item.version > version
            ]

    def _cleanup_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=2)
        expired = [
            run_id
            for run_id, progress in self._runs.items()
            if progress.updatedAt < cutoff and progress.status in {"completed", "failed"}
        ]
        for run_id in expired:
            self._runs.pop(run_id, None)
            self._versions.pop(run_id, None)
            self._history.pop(run_id, None)


progress_tracker = ProgressTracker()
