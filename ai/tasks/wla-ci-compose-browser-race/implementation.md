# Implementation Notes

## Summary

- `Overview` now derives onboarding visibility during render from resolved dashboard state,
  the explicit query parameter, and a stateful dismissal flag. This removes the stale
  `useEffect` frame while preserving explicit onboarding links and persisted dismissal.
- `SetupStatus` reports completion only after both role and readiness state resolve.
- The browser fixture uses a UUID plus retry/repeat identifiers so Playwright retries start
  with unique client, connector, and mapping records. The mutually exclusive onboarding and
  setup assertions now use separate navigations.
- Main push workflow runs use commit-specific concurrency groups and do not cancel one
  another; pull-request runs retain cancellation of superseded runs.
- No runtime dependencies, package manifests, lockfiles, backend behavior, or Compose
  definitions were changed.

## Commands Run

- `npm ci` in `ui/` — passed; 141 packages installed, audit reported 0 vulnerabilities.
- `npm test -- src/components/SetupStatus.test.tsx` — passed, 1 file / 3 tests.
- `npm test -- --config /tmp/wla-ci-compose-browser-race-vitest.config.ts` — passed after the
  connector assertion correction, 49 files / 234 tests. The plain `npm test` invocation was
  blocked before test startup because `ui/node_modules/.vite-temp` is owned by `nobody` and is
  not writable by this checkout user; the temporary config redirected only Vite's generated
  cache to `/tmp`.
- `npm run build` — passed; Vite emitted only the existing config-loader and bundle-size
  warnings.
- `npx playwright test --config playwright.config.ts --list` — passed; production-readiness
  spec discovered.
- `ruff check .` — passed.
- `uv lock --check` — passed using a temporary writable cache.
- `git diff --check` — passed.
- Workflow YAML parsed successfully with Python/PyYAML; actionlint was unavailable.
- Direct `mypy src tests` and the backend coverage command could not complete because this
  checkout environment lacks the `slowapi` dependency and the installed package import path.
  The offline `uv run` fallback was unavailable with the default read-only cache.
- `WAIT_COMPOSE_RUN_BROWSER=true scripts/test_compose_integration.sh` — blocked before service
  startup because the environment denied access to `/var/run/docker.sock`.

## Acceptance-Test Correction

- The orchestrator executed the real Compose/browser acceptance test externally in a
  Docker-capable environment. It found one missed generated-fixture assertion at line 61:
  the locator still used the hardcoded `Browser Smoke Connector` while the fixture creates
  `connectorName` with a per-attempt suffix.
- The assertion now uses `connectorName` with `{ exact: true }`. A full re-audit found no other
  hardcoded generated fixture values; `browser-client-id`, `browser-client-secret`, and
  `browser-tenant` remain intentionally constant provider credential values.
- The Compose/browser test was not rerun locally because this environment has no Docker socket;
  it must not be considered locally passed.

## Files Touched

- `.github/workflows/test.yml`
- `ui/e2e/production-readiness.spec.ts`
- `ui/src/components/SetupStatus.test.tsx`
- `ui/src/components/SetupStatus.tsx`
- `ui/src/screens/Overview.tsx`
- `ai/tasks/wla-ci-compose-browser-race/implementation.md`
- `ai/tasks/wla-ci-compose-browser-race/review.md`
- `ai/tasks/wla-ci-compose-browser-race/status.json`

## Follow-Up

- Run the Compose/browser acceptance test in a Docker-capable environment, including the
  retry-isolation scenario, before merge.
- Required Kimi read-only review and Claude final gate remain pending. No commit, push, or PR
  was created.
