# Time Series Forecast Lab

Interactive lab for importing time-series data, comparing multiple forecasting models with a holdout backtest, reviewing residuals and metrics, selecting a final model, and saving experiment history without storing the original uploaded file.

## v0.4 Roadmap

Development is converging on the [Transparent Time Series Experiment Platform](docs/V0.4_TRANSPARENT_PLATFORM.md): observable, explainable, reproducible, and benchmarkable experiments. v0.4 does not add new forecasting models.

## Current Scope

v0.2 keeps the v0.1 forecast workflow intact and adds product hardening:

- Chinese product shell and localized forecast workflow.
- Extended model registry metadata with install status, dependency package, install command, model family, paper metadata, and display priority.
- Optional lag-feature regression adapters for XGBoost, LightGBM, and Random Forest.
- Planned model registry entries for N-BEATS, N-HiTS, PatchTST, Chronos, Moirai, and Lag-Llama. These are visible in the model library but not selectable for experiments until adapters are connected.
- DeepSeek settings page for API Key, Base URL, model selection, and connection testing.
- DeepSeek report generation API that creates Chinese Markdown reports from experiment summaries.
- Report history stored in SQLite without storing DeepSeek API Keys.

v0.1 focuses on real-file acceptance and core forecast workflow hardening:

- CSV, XLSX, and XLS upload preview.
- Excel sheet selection.
- Backend parsing with a 100-row frontend preview.
- Common datetime formats, including `yyyyMMdd`, scientific notation such as `2.0230102E7`, Excel serial dates, Unix seconds, and Unix milliseconds.
- Aggregated time series mode and raw detail aggregation mode.
- Holdout split with `residual = actual - predicted`.
- MSE, MAE, RMSE, and WAPE.
- Model failure isolation.
- SQLite experiment history that does not depend on the original upload file.
- Eight ECharts panels plus model leaderboard and final forecast chart.

## Local URLs

- Frontend: `http://127.0.0.1:5173`
- Backend health: `http://127.0.0.1:8100/api/health`

## Backend Startup

```powershell
cd backend
uv run --with-requirements requirements.txt --with-requirements requirements-optional.txt uvicorn app.main:app --reload --port 8100
```

Python venv alternative:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-optional.txt
uvicorn app.main:app --reload --port 8100
```

## Frontend Startup

```powershell
cd frontend
npm install
npm run dev
```

## Optional Model Dependencies

Prophet, TimesFM, XGBoost, LightGBM, and Random Forest rely on `requirements-optional.txt`.

默认建议在本地开发和一键重建时一起安装这份依赖，这样模型状态不会在重建后回退成 `not_installed`：

```powershell
cd backend
pip install -r requirements-optional.txt
```

`deploy/local_rebuild.py` 现在会默认重装基础依赖 + 可选模型依赖；只有在明确传入 `--skip-optional-models` 时才会跳过。

Prophet may require platform-specific build dependencies depending on your Python environment.

TimesFM may download model weights the first time it runs. Cache locations:

```text
HF_HOME=backend/.model_cache/huggingface
TIMESFM_CACHE_DIR=backend/.model_cache/timesfm
```

If TimesFM is unavailable, only the TimesFM model is marked failed or unavailable. Other selected models continue running and remain eligible for ranking.

XGBoost, LightGBM, and Random Forest use the same lag-feature regression adapter:

```text
lag_1, lag_2, lag_3, lag_7
rolling_mean_3, rolling_mean_7, rolling_std_7
time_index, day_of_week, month
```

If an optional package is missing, the model library shows `not_installed`, the experiment selector disables that model, and direct API requests still isolate the failure to that one model.

## DeepSeek Report Setup

The frontend settings page is available at:

```text
/settings
```

It supports:

- API Key input with show/hide.
- Base URL, default `https://api.deepseek.com`.
- Model selection, default `deepseek-v4-flash`.
- Test connection button.
- Session-only storage by default.
- Optional local browser storage if the user explicitly enables "remember locally".

Security policy:

- The DeepSeek API Key is never written to SQLite.
- The DeepSeek API Key is never written to experiment history.
- The backend only uses the API Key temporarily for connection testing and report generation.
- Reports send experiment metadata, diagnostics, ranked metrics, residual summaries, model logs, and final forecast summaries.
- Reports do not send original uploaded files or complete raw source tables.

DeepSeek APIs:

```text
POST /api/llm/deepseek/test
POST /api/reports/generate
```

## GPU Detection

Backend device detection is exposed at:

```text
GET /api/models/device
```

Priority is:

```text
cuda > mps > cpu
```

The device response distinguishes NVIDIA hardware detection from CUDA runtime availability. A machine can have an NVIDIA GPU while a CPU-only PyTorch build is installed; in that case `hardwareDetected=true`, `runtimeAvailable=false`, and models continue on CPU with a readable reason.

Windows CUDA installation for the tested CUDA 13.2 wheel:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install --force-reinstall -r requirements-gpu-cu132.txt
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

The current machine was verified with an NVIDIA RTX 4060 Ti and `torch 2.12.1+cu132`. Select the PyTorch wheel matching the CUDA version supported by the target machine when deploying elsewhere.

## Test Commands
Frontend:

```powershell
cd frontend
npm run typecheck
npm run build
```

Backend:

```powershell
cd backend
uv run --cache-dir .uv-cache --with-requirements requirements.txt python -m compileall app
uv run --cache-dir .uv-cache --with-requirements requirements.txt pytest
```

If the local dependency cache is already populated and network access is restricted, add `--offline`.

## Production Deployment

The production bootstrap entrypoint is:

```text
deploy/server-bootstrap.sh
```

It installs Docker, writes Docker daemon mirror and DNS settings that suit mainland China network conditions, restarts Docker, pre-pulls the required base images, and then runs:

```text
docker compose -f docker-compose.prod.yml up -d --build
```

The bootstrap script honors these optional environment variables:

- `APP_DIR`
- `DOCKER_REGISTRY_MIRRORS`
- `DOCKER_DNS_SERVERS`
- `BACKEND_PYTHON_BASE_IMAGE`
- `BACKEND_DEBIAN_MIRROR`
- `BACKEND_DEBIAN_SECURITY_MIRROR`
- `FRONTEND_NODE_BASE_IMAGE`
- `FRONTEND_NGINX_BASE_IMAGE`

## Example Files

Canonical acceptance fixtures are generated by:

```powershell
cd backend
uv run --with-requirements requirements.txt python tests/generate_fixtures.py
```

Fixture paths:

- `backend/tests/fixtures/daily_air_passengers.csv`
- `backend/tests/fixtures/monthly_air_passengers.xlsx`
- `backend/tests/fixtures/raw_flight_detail_multi_sheet.xlsx`
- `backend/tests/fixtures/invalid_date.csv`
- `backend/tests/fixtures/duplicate_dates.xlsx`
- `backend/tests/fixtures/missing_values.xlsx`
- `backend/tests/fixtures/short_series.csv`
- `backend/tests/fixtures/legacy_daily_air_passengers.xls`

Frontend fixture notes live in `frontend/src/fixtures/README.md`.

## Manual v0.1 Acceptance Flow

1. Start the backend and frontend.
2. Upload `backend/tests/fixtures/raw_flight_detail_multi_sheet.xlsx`.
3. Select the `domestic` sheet.
4. Choose raw detail data mode.
5. Select `flight_date` as the time column.
6. Select `passenger_count` as the target column.
7. Select `sum` aggregation.
8. Select Naive, Seasonal Naive, Moving Average, ARIMA, ETS, Prophet, and TimesFM.
9. Set `horizon=7`.
10. Confirm `testSize=7`.
11. Run the holdout backtest.
12. Review the leaderboard and all eight chart panels.
13. Select the recommended model as the final model.
14. Run final forecast.
15. Open experiment history.
16. Open the experiment detail page and confirm charts replay without the original file.
17. Confirm the upload file was removed from `backend/tmp/uploads`.

## Storage Policy

Temporary uploaded files are stored under `backend/tmp/uploads` only for the active workflow. The backend logs:

- `upload temp file created`
- `upload temp file deleted`
- `stale upload temp file cleaned`

Experiment history stores:

- Experiment metadata.
- File name and sheet name.
- Selected columns and configuration.
- Metrics and model logs.
- Backtest chart data.
- Aggregated history and final forecast outputs.

Experiment history does not store:

- Original uploaded files.
- Full raw source tables.
- Sensitive row-level business details.

## Known v0.1 Limits

- No true multivariate joint modeling; multiple targets run as separate univariate forecasts.
- No covariates or holiday features.
- No rolling backtest.
- No automatic hyperparameter tuning.
- Prophet and TimesFM are optional and may fail independently if dependencies or model cache are unavailable.
- XGBoost, LightGBM, and Random Forest are optional and require `requirements-optional.txt`.
- Deep learning and foundation model entries beyond TimesFM are registry placeholders until adapters are implemented.
- DeepSeek report quality depends on the user's API Key, quota, selected model, and network availability.
- ECharts is bundled into the frontend build; production build currently reports a chunk-size warning.
