# DeepSeek report hotfix — 2026-09-10

## Subsequent report synchronization

Current release: `/opt/tsfl-releases/20260910002616-7f6f493-report-sync`.
Audit/backup: `/opt/tsfl-releases/deploy-records/20260910002616-report-sync`.
The complete report service now matches the local working-tree file, SHA-256
`456ba92611311945561ed3a83c1dfba45525c5b77e3cb1f3f8ddd56aa9f314ae`.
Includes business-first writing instructions, compact context, local report continuation
logic, differentiated HTTP error messages, and the previous production empty-response fix.
Local report tests: 15 passed. Both services restarted and health checks passed.
Database dump and upload digests before/after deployment match. Counts at sync time:
8 users, 13 workspaces, 25 memberships, 15 experiments, 2 reports, 6 temporary files.
The report count was already 2 before this synchronization; no report was regenerated.
Other local changes to forecasting, parsing or frontend charts were not deployed.
Both environments still use Git baseline `7f6f493`; local report changes are uncommitted,
so deployment identification must include the service file hash, not only the Git hash.
The local launchctl service uses `/private/tmp/tsfl-deepseek-0910/local_preserve.py`
with the repo backend on PYTHONPATH, skipping migrations/cleanup during startup.

## Initial hotfix

Production base: `7f6f493c6cd36b641db90ac216312ecfa2d17028`.
Release: `/opt/tsfl-releases/20260910001217-7f6f493-deepseek-fix`.
Prior release: `/opt/tsfl-releases/20260823205602-7f6f493`.
Audit and SQLite backup: `/opt/tsfl-releases/deploy-records/20260910001217-deepseek-fix/`.

This hotfix is applied to the production baseline, not the local dirty working tree.
Only `backend/app/services/deepseek.py` application code changed. Its SHA-256 is
`7b3877366561957cf91af650e4935159658ed56be89652b2f4429c148efb33c8`.

Report requests explicitly disable Thinking, retry empty content once, validate response
structure and expose specific empty/malformed/filtered-response errors. Logs contain
attempt count, a fixed allowlist of finish reasons and a boolean indicating reasoning
presence; no key, prompt, report or reasoning text is logged.

Six offline regression scenarios passed against the actual patched function:
normal content, recovery after empty content, repeated empty content, missing choices,
missing message, and upstream content filtering. Live paid API generation was not tested.

## Data-preserving startup

`backend/deploy_preserve.py` wraps the existing application, disabling database
bootstrap/migration and expired-upload cleanup before importing it. The systemd drop-in
`/etc/systemd/system/time-series-forecast-lab.service.d/99-deepseek-preserve.conf`
selects this entrypoint. This also applies to subsequent restarts of this release.
Normal application operations (new experiments, reports, sessions) still write normally.
Future releases requiring schema changes must deliberately replace this entrypoint/drop-in.

Deployment stopped the backend, backed up SQLite, switched the release, then compared
`before.json` and `after.json`: complete database SQL dump digest and all temporary-file
digests matched exactly. Counts: 8 users, 13 workspaces, 25 workspace memberships,
15 experiments, 1 report, 6 temporary/upload files. No database migration was run.
Public `/api/health` and homepage passed after switching.

## Rollback

Keep the prior release and backup. To roll back without startup data mutations, copy
the new release's `backend/deploy_preserve.py` to an audit directory, point the service
at `uvicorn --app-dir <audit-directory> deploy_preserve:app`, set
`PYTHONPATH=/opt/time-series-forecast-lab/backend`, atomically repoint the main symlink
to the prior release, daemon-reload and restart. Do not restore the database backup
over newer user work. Verify health and data digests after rollback.
