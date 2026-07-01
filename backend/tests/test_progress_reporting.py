from __future__ import annotations

from uuid import uuid4

from app.schemas import ModelProgress
from app.services.progress_tracker import progress_tracker


def test_progress_tracker_updates_model_and_terminal_state():
    run_id = f"test_{uuid4().hex}"
    progress_tracker.start(
        run_id,
        "backtest",
        [ModelProgress(modelId="naive", modelName="Naive", targetColumn="value")],
        "Preparing.",
    )

    progress_tracker.update_model(
        run_id,
        "value",
        "naive",
        status="fitting",
        percent=10,
        message="Fitting.",
    )
    fitting = progress_tracker.get(run_id)
    assert fitting is not None
    assert fitting.models[0].status == "fitting"
    assert fitting.models[0].percent == 10
    assert fitting.version > 1

    progress_tracker.update_model(
        run_id,
        "value",
        "naive",
        status="success",
        percent=100,
        message="Complete.",
        fitSeconds=0.2,
        predictSeconds=0.1,
    )
    progress_tracker.finish(run_id, "completed", "Experiment complete.")
    completed = progress_tracker.get(run_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.overallPercent == 100
    assert completed.completedModels == 1
    assert completed.models[0].fitSeconds == 0.2
    history = progress_tracker.get_after(run_id, 1)
    assert [snapshot.models[0].status for snapshot in history[:2]] == ["fitting", "success"]
    assert history[-1].status == "completed"
