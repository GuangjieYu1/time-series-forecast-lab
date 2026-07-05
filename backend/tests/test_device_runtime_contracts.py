from __future__ import annotations

from app.core import gpu
from app.schemas import ModelProgress
from app.services.runtime_events import make_timeline_entry
from app.services.runtime_tracker import RuntimeTracker


def _torch_info(*, cuda_available: bool, cuda_runtime: str | None):
    return {
        "installed": True,
        "version": "2.12.1+cu132" if cuda_runtime else "2.12.1+cpu",
        "build": "cuda" if cuda_runtime else "cpu",
        "cudaRuntime": cuda_runtime,
        "cudaAvailable": cuda_available,
        "mpsAvailable": False,
        "deviceName": "NVIDIA GeForce RTX 4060 Ti" if cuda_available else None,
        "deviceMemoryMb": 8188 if cuda_available else None,
    }


def test_device_info_distinguishes_hardware_from_cpu_torch(monkeypatch):
    monkeypatch.setattr(gpu, "get_memory_info", lambda: {"memoryTotalMb": 32768, "memoryAvailableMb": 16384})
    monkeypatch.setattr(
        gpu,
        "_detect_nvidia_hardware",
        lambda: {"name": "NVIDIA GeForce RTX 4060 Ti", "memoryTotalMb": 8188, "driverVersion": "610.62"},
    )
    monkeypatch.setattr(gpu, "_torch_capabilities", lambda: _torch_info(cuda_available=False, cuda_runtime=None))

    info = gpu.get_device_info()

    assert info["device"] == "cpu"
    assert info["accelerator"]["hardwareDetected"] is True
    assert info["accelerator"]["runtimeAvailable"] is False
    assert "CPU 构建" in info["accelerator"]["reason"]


def test_device_info_reports_cuda_runtime(monkeypatch):
    monkeypatch.setattr(gpu, "get_memory_info", lambda: {"memoryTotalMb": 32768, "memoryAvailableMb": 16384})
    monkeypatch.setattr(
        gpu,
        "_detect_nvidia_hardware",
        lambda: {"name": "NVIDIA GeForce RTX 4060 Ti", "memoryTotalMb": 8188, "driverVersion": "610.62"},
    )
    monkeypatch.setattr(gpu, "_torch_capabilities", lambda: _torch_info(cuda_available=True, cuda_runtime="13.2"))

    info = gpu.get_device_info()

    assert info["device"] == "cuda"
    assert info["accelerator"]["runtimeAvailable"] is True
    assert info["accelerator"]["cudaRuntime"] == "13.2"


def test_timeline_level_defaults_and_optimization_failure_is_warning():
    default_entry = make_timeline_entry(stage="training", status="running", message="Training")
    assert default_entry.level == "info"

    tracker = RuntimeTracker()
    tracker.start(
        "run_warning",
        kind="backtest",
        model_rows=[ModelProgress(modelId="lightgbm", modelName="LightGBM", targetColumn="value")],
        parameter_strategy="auto",
        message="Starting",
    )
    tracker.update_optimization(
        "run_warning",
        target_column="value",
        model_id="lightgbm",
        current_trial=2,
        total_trials=5,
        message="Trial #2 评估失败：invalid params",
        trial_status="failed",
    )
    detail = tracker.get("run_warning")

    assert detail is not None
    assert detail.timeline[-1].level == "warn"
    assert detail.timeline[-1].status == "running"
    assert detail.logs[-1].level == "warn"

def test_timesfm_loader_disables_torch_compile(monkeypatch):
    import sys
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.models.timesfm_model import TimesFmModel

    captured = {}

    class FakeLoadedModel:
        def compile(self, forecast_config, **kwargs):
            captured["compile_kwargs"] = kwargs

    class FakeTimesFm:
        DEFAULT_REPO_ID = "fake/timesfm"

        @classmethod
        def from_pretrained(cls, source, **kwargs):
            captured["source"] = source
            captured["load_kwargs"] = kwargs
            return FakeLoadedModel()

    fake_module = SimpleNamespace(
        configs=SimpleNamespace(ForecastConfig=lambda **kwargs: kwargs),
        TimesFM_2p5_200M_torch=FakeTimesFm,
    )
    monkeypatch.setitem(sys.modules, "timesfm", fake_module)

    model = TimesFmModel(max_context=32)
    times = [datetime(2026, 1, 1) + timedelta(days=index) for index in range(32)]
    model.fit(times, [float(index) for index in range(32)], "D")

    assert captured["load_kwargs"]["torch_compile"] is False