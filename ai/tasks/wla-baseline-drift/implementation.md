# Implementation Notes

## Summary

- Added migration 11 and tenant-scoped persistence for versioned `client_baselines`, with atomic first acceptance and acceptance switching.
- Added normalized baseline composition across Microsoft posture summaries, environment graph counts, canonical asset metadata, and connector readiness. Persisted data is redacted normalized state and references, never raw provider payloads.
- Added section-aware drift comparison with ordering-insensitive canonicalization, numeric posture polarity, unavailable-source handling, and best-effort client-scoped approved-change correlation.
- Added guarded admin/MSP routes, `baseline_snapshot` scheduling, sanitized scheduler audit failures, route surface classification, documentation, and a Clients Baseline tab.
- Added the required backend acceptance matrix across lifecycle, source coverage, all drift classifications, list normalization, approval correlation and isolation, all four routes, scheduler execution/failure hygiene, and scoped store CRUD. The two listed pin files without migration assertions were verified and left unchanged.

## Acceptance Matrix Coverage

- `tests/test_baseline.py`: atomic acceptance and versioning, blocked/not-configured coverage gates, added/removed/changed/worsened/improved/resolved drift, hash short-circuiting for reordered lists, time-windowed approval correlation, and wrong-client baseline CRUD closure.
- `tests/test_baseline.py`: final branch cases for source failures, status normalization, populated and empty store sections, connector cursor aggregation, baseline fallback, entity maps, polarity misses, and correlation-window boundaries.
- `tests/test_microsoft_admin_insights.py`: stable summary projection and remaining diagnostic empty/failure surface branches using the shared Graph stubs.
- `tests/test_api.py`: unauthenticated and non-MSP authorization for all baseline endpoints, demo-mode write refusal, live-probing gate, unknown client/version 404s, successful endpoint flow, and baseline audit events.
- `tests/test_scheduler.py`: `baseline_snapshot` target validation, registration, stubbed execution, completion audit, and sanitized failure audit.

## Commands Run

- `ruff check src tests` — passed; targeted changed-file Ruff checks also passed.
- `mypy src tests` — implementation checks passed; the full repository reported only two existing unused-ignore findings in `src/wait_local_agent/cloud_connectors/aws.py` and `src/wait_local_agent/nsight.py`.
- `PYTHONPATH=src python -m compileall -q src/wait_local_agent src/packs` — passed.
- `ui/node_modules/.bin/tsc -b ui/tsconfig.json --pretty false` — passed after adding the Baseline screen test.
- `npm --prefix ui run test -- --run src/screens/__tests__/Clients.test.tsx --reporter=dot` — passed: 1 file, 12 tests.
- `git diff --check` — passed.
- `npm --prefix ui install --package-lock-only --ignore-scripts --offline` — current compatible lockfile/dependencies remained up to date; no dependency changes.
- `uv lock --check` — environment-limited because the global uv cache is read-only; no lockfile was changed.
- `bandit -r src` — unavailable because Bandit is not installed.
- Backend pytest and Playwright were intentionally not run because the task plan prohibits both.
- The final coverage-gap test additions were linted and compiled; pytest remains intentionally unrun per the final coverage task instruction.
- No commit or push was performed, per the task contract.

## Files Touched

- Backend: `src/wait_local_agent/{baseline.py,models.py,store.py,scheduler.py,api/app.py}` and `src/packs/microsoft_admin/{insights.py,core.py}`.
- Tests: `tests/test_baseline.py`, `tests/test_spine_p0.py`, `tests/test_principals.py`, `tests/test_wla_a_pr3b_poll_lease.py`, `tests/test_wla_f1_operational_graph.py`, `tests/test_wla_p1_clients.py`, and `tests/test_wla_p2_provenance.py`.
- UI: `ui/src/api/types.ts`, `ui/src/screens/Clients.tsx`, and `ui/src/screens/__tests__/Clients.test.tsx`.
- Documentation and task state: `docs/ai-workflow/surface-coverage.json`, `docs/concepts/baseline-drift.md`, and this task's three artifacts.

## Follow-Up

- Required read-only Claude cross-family review and final human merge/deploy gate remain pending.
- Run the full backend coverage suite, Bandit, and lock verification in a provisioned environment with the repository's complete development dependencies.

- 2026-09-01T15:37:00Z: Launching Codex gpt-5.6-luna implementation through the artifact runtime in `/home/josephp/wait-local-agent-main`.

- 2026-09-01T16:04:25Z: Codex gpt-5.6-luna completed successfully; repository verification is next.
- 2026-09-01: Added focused Microsoft admin insight tests for empty/failed dashboard surfaces and all present/absent diagnostic findings. Pytest was intentionally not run per task instruction.
