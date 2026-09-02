# Implementation Notes

## Summary

- Added appliance-level encrypted backup scheduling, persisted backup-run metadata,
  retention handling, operator status/run APIs, audit events, and Overview status.
- Added the `backup` schedule kind to the existing Scheduler/Scheduled Jobs flows;
  the runner is constructor-injected for tests and defaults to the existing
  `backup.py` Fernet path when application settings are supplied.
- Added migration 13 (`backup_runs`), default retention of seven artifacts via
  `backup.retention_count`, sanitized failure summaries, and non-fatal recorded
  retention-pruning failures.
- Documented the operator-managed signed update and restore-based rollback
  procedure. `Settings.tsx` was not changed.

## Commands Run

- `ruff check` on changed Python files: passed.
- Targeted `mypy` for `backup.py`, `models.py`, `scheduler.py`, and `store.py`:
  passed.
- Python compileall and `/usr/bin/git diff --check`: passed.
- `python scripts/public_surface_audit.py`: passed.
- `npm test`: 83 files and 471 tests passed.
- `npm run build`: passed with the repository's existing Vite config and chunk-size
  warnings.
- Direct populated-environment smoke: backup run succeeded and migration 13 was
  applied.
- Full `mypy src tests` remains blocked by six pre-existing missing `slowapi`
  imports in the local environment; Bandit is not installed. Pytest and
  Playwright were intentionally not run per the task plan.

## Files Touched

- `src/wait_local_agent/{api/app.py,backup.py,models.py,scheduler.py,store.py}`
- `tests/test_backup_lifecycle.py` and migration pin tests in
  `tests/{test_principals.py,test_spine_p0.py,test_wla_a_pr3b_poll_lease.py,test_wla_p1_clients.py}`
- `ui/src/api/types.ts`, `ui/src/screens/{Overview.tsx,ScheduledJobs.tsx,Schedules.tsx}`
  and `ui/tests/ScheduledJobs.test.tsx`
- `docs/operations/{backups-and-vault.md,updates.md}` and
  `docs/ai-workflow/surface-coverage.json`
- This task's `implementation.md`, `review.md`, and `status.json`

## Follow-Up

- Run the required read-only Kimi review and Claude final gate before any human
  merge. No commit or PR was created because the plan explicitly requires the
  human-controlled merge/deploy boundary.
- If full repository validation is required, provide/install the repository's
  missing Python runtime dependencies (`slowapi`, `itsdangerous`) and Bandit in
  the validation environment without changing project dependencies.

- 2026-09-01T21:35:58Z: Launching Codex gpt-5.6-luna implementation through the artifact runtime in /home/josephp/wait-local-agent-main.

- 2026-09-01T22:01:02Z: Codex gpt-5.6-luna completed successfully; repository verification is next.

- Coverage follow-up: added deterministic lifecycle tests for backup path
  confinement, Fernet-key error handling, restore validation, restore-exercise
  failure cleanup, and retention boundary/protected-file behavior. Pytest was
  intentionally not run per the task request.
