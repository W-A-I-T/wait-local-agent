# Implementation Notes

## Summary

- Added instance-backed NinjaOne, Datto RMM, and N-able N-central adapters to
  the existing connector factory. Vault credentials are isolated from
  non-secret base URL and tenant-map configuration; instance clients are
  forced read-only.
- Added fail-closed RMM resolution for client-scoped graph sync: client
  instance, then MSP-wide instance, then environment configuration, then the
  local collector. Ambiguous active instance tiers return a safe error.
- Extended create-time validation, the Connector Instances screen and setup
  metadata, both Connector Instances UI test files, focused backend tests, and
  configuration documentation.

## Commands Run

- `ruff check src/wait_local_agent/api/app.py src/wait_local_agent/connector_factory.py src/wait_local_agent/rmm.py tests/test_connector_factory.py tests/test_rmm.py` — pass.
- `mypy src/wait_local_agent/connector_factory.py src/wait_local_agent/rmm.py tests/test_connector_factory.py tests/test_rmm.py` — pass.
- `mypy src tests` — changed files clean; six pre-existing missing `slowapi` stubs remain.
- `/usr/bin/python3 -m compileall -q src tests` — pass.
- `npm run build --if-present` in `ui/` — pass; existing Vite native-config and chunk-size warnings remain.
- Focused Vitest for both Connector Instances suites and setup metadata — 3 files, 22 tests passed.
- `bandit -r src` and `/usr/bin/python3 -m bandit -r src` — unavailable; Bandit is not installed.
- Pytest and Playwright were not run per the task contract.

## Files Touched

- `src/wait_local_agent/connector_factory.py`
- `src/wait_local_agent/rmm.py`
- `src/wait_local_agent/api/app.py`
- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/lib/connectorSetup.ts`
- `ui/src/screens/__tests__/ConnectorInstances.test.tsx`
- `ui/tests/ConnectorInstances.test.tsx`
- `ui/tests/connectorSetup.test.ts`
- `tests/test_connector_factory.py`
- `tests/test_rmm.py`
- `docs/getting-started/configuration.md`
- `ai/tasks/wla-rmm-instances/implementation.md`
- `ai/tasks/wla-rmm-instances/review.md`
- `ai/tasks/wla-rmm-instances/status.json`

## Follow-Up

- Claude final-gate review should run the prohibited-by-plan Python suite and
  coverage in its approved environment, plus Bandit/gitleaks if available.
- No dependency or provider API version changed; the existing Vite 8.2.2 and
  pinned provider client implementations were reused.

- 2026-09-01T06:05:36Z: Launching Codex gpt-5.6-luna implementation through the artifact runtime in /home/josephp/wait-local-agent-main.

- 2026-09-01T06:22:28Z: Codex gpt-5.6-luna completed successfully; repository verification is next.

- 2026-09-01: Added focused tests for the remaining RMM precedence, fail-closed
  resolution, local collector, legacy environment, and connector config
  validation branches. Pytest was intentionally not run per task instructions.

- 2026-09-01: Added the final coverage micro-top-up for Datto RMM, NinjaOne,
  N-central, and route-specific request-validation redaction branches. Pytest
  was not run per task instructions; no commit or push was performed.
