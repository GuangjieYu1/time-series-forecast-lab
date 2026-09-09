# Shared standard environment

Local and ECS use Python **3.11.13**, `backend/requirements-standard.lock`, and
`deploy/standard.env`. The lock covers macOS and Linux; platform-specific runtime
packages may differ, but common Python packages use identical pinned versions.
Install with uv 0.11.7:

```sh
uv venv --python 3.11.13 backend/.venv-standard
uv pip sync --python backend/.venv-standard/bin/python backend/requirements-standard.lock
```

macOS additionally requires `brew install libomp` for XGBoost/LightGBM.
Use `npm ci` and Node 24.14.1 for the frontend. Build it locally with `npm run build`
and deploy the same `dist` artifact to the small ECS instance.

## Models and reproducibility

Standard enables Naive, Seasonal Naive, Moving Average, ARIMA, ETS, Prophet,
Random Forest, XGBoost and LightGBM. TimesFM is explicitly unavailable even if
its package happens to be installed. Other planned model adapters remain planned.
In standard mode auto-tuning completes its fixed candidate count instead of
stopping on elapsed time, so machine speed does not change the candidate budget.
Standard XGBoost uses CPU histogram trees and full row/column sampling; this avoids
the cross-compiler sampling differences observed with the full profile's 0.9 fractions.
Keep the same input, aggregation, frequency, seed and model parameters when comparing.
Native floating-point arithmetic, Prophet uncertainty sampling and external LLM
sampling can still produce small numerical or textual differences across platforms.

`GET /api/health` reports Python version, model profile, source fingerprint and
dependency-lock fingerprint. `deploy/verify_standard.py` runs a read-only synthetic
probe of the nine models and records actual library versions. It never reads users,
reports or experiments. Run with the standard environment and thread limits set.

## Preserve existing data

`PRESERVE_EXISTING_DATA=true` skips database initialization/migration and startup
expiry cleanup. It fails if the database does not exist. Ordinary user operations
continue writing normally. Initial installations and future schema migrations must
explicitly initialize/migrate a backed-up database with this setting disabled.
No source or environment update should overwrite database, upload or model-cache paths.

## Local full environment

The original `backend/.venv` and model cache are retained for full-model work.
It is not the default service environment. For a separate full backend, use that
interpreter with `MODEL_PROFILE=full` on another port (for example 8101), keeping
`PRESERVE_EXISTING_DATA=true` when using the existing database. No full service is
started automatically. The standard service remains on port 8100.

`deploy/local_rebuild.py` defaults to standard on macOS/Linux and uses the locked
environment plus `npm ci`. On macOS it submits the backend to launchctl so terminal
cleanup does not terminate it. `--profile full` explicitly selects the original env.
Windows remains on the prior full setup because this lock targets macOS/Linux only.

## Release procedure

Commit the scoped code/tests/lock changes to develop. Use that commit's archive and
the verified frontend archive for a new release directory. Link shared data/tmp/cache,
use a newly prepared standard venv, and run the synthetic probe before switching.
During the brief switch: stop backend, online-backup SQLite, record complete database
dump and upload hashes, replace the current symlink atomically, start using standard.env,
check health, then compare data fingerprints. Retain the previous release, environment
and systemd configuration for rollback. Never restore an old DB over newer user writes.
