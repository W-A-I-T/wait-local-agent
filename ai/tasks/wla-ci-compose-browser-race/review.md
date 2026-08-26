# Review

## Changed Files

- `.github/workflows/test.yml`
- `ui/e2e/production-readiness.spec.ts`
- `ui/src/components/SetupStatus.test.tsx`
- `ui/src/components/SetupStatus.tsx`
- `ui/src/screens/Overview.tsx`
- Task artifacts under `ai/tasks/wla-ci-compose-browser-race/`

## Risk Areas

- Onboarding visibility is now synchronous with resolved role/readiness state, preventing a
  contradictory `SetupStatus`/wizard frame. Explicit `?onboarding=1` still overrides dismissal;
  dismissal still persists and removes the query parameter with `replace: true`.
- Fixture uniqueness includes `testInfo.retry`, `testInfo.repeatEachIndex`, and `randomUUID()`;
  retries therefore do not reuse the first attempt's database records.
- The workflow keeps every existing backend, UI, security, gitleaks, desktop, and
  compose-browser gate unchanged. `ui/playwright.config.ts` still has `retries: 1` in CI.
- No auth, secrets, backend, API, or data-boundary code was changed. The generated fixture
  identifiers are local test values and are not credentials.

## Version & Compatibility Evidence

- No version or API changes were made. The existing `actions/checkout@v7`,
  `actions/setup-node@v7`, and `actions/setup-python@v7` pins remain unchanged.
- GitHub documents that concurrency group names may use dynamic context expressions and that
  `cancel-in-progress` may be conditional: [Control the concurrency of workflows and jobs](https://docs.github.com/en/enterprise-cloud%40latest/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Questions

- No implementation questions. Compose/browser execution remains an environment-level follow-up
  because Docker API access was denied.

## Test Results

- Passed: focused SetupStatus test (3/3), corrected full UI suite (49 files / 234 tests), UI
  build, Playwright test discovery, `ruff check .`, `uv lock --check`, workflow YAML parse, and
  `git diff --check`. The suite ran through `npm test` with a temporary config that redirected
  Vite's generated cache to `/tmp`; plain `npm test` could not start because the existing
  `ui/node_modules/.vite-temp` directory is owned by `nobody` and is not writable here.
- Backend `mypy` could not complete because `slowapi` is not installed in the direct environment;
  backend pytest could not import `wait_local_agent` from this checkout. The offline `uv run`
  fallback could not initialize the default read-only uv cache. `bandit` and `pip-audit` are not
  installed locally. Their workflow definitions were verified unchanged.
- Blocked: actual Compose/browser e2e run due to permission denied on `/var/run/docker.sock`.

## Orchestrator Acceptance Correction

- The orchestrator executed the real Compose/browser acceptance test externally in a
  Docker-capable environment. It failed at line 61 because the exact-match locator still
  hardcoded `Browser Smoke Connector` after fixture names became suffixed.
- The locator now uses `connectorName` and retains `{ exact: true }`.
- Re-audit result: all generated client, connector, and mapping assertions/locators use their
  generated variables. The provider credential literals remain intentionally constant.
- The Compose/browser test is not claimed as passed locally; Docker is unavailable here.

## Orchestrator Verification Evidence (Claude, Docker-capable environment)

Executed against the corrected head on branch `ai/wla-ci-compose-browser-race-green`.
Ports 8799/5199 were used because 8788/5173 are held by unrelated local dev processes.

- `WAIT_COMPOSE_RUN_BROWSER=true scripts/test_compose_integration.sh` — **PASSED**, exit 0,
  `1 passed (12.8s)`. This is exactly what the `compose-browser` CI job runs.
- `npm test` in `ui/` — **PASSED**, 49 files / 234 tests, run directly by the orchestrator.
- Race + isolation guard: `--repeat-each=5 --workers=1` with `CI=1` against a **single shared
  database** — **5/5 PASSED**. This proves both that the render race is eliminated and that the
  per-attempt fixture identifiers prevent collisions, which is the property `retries: 1` needs.
- An earlier `--repeat-each=5` run showed 3 failures. Those were **not** a code defect: the API
  rate limiter (`rate_limit_general` 100/minute, `rate_limit_connector` 10/minute) rejected the
  requests with "The appliance is handling too many requests right now." Re-running with
  `WAIT_RATE_LIMIT_ENABLED=false` via an external Compose override (no repository change) gave
  5/5. A first attempt at 5 parallel workers was an orchestrator harness error, not a product
  issue; CI runs single-worker.
- Workflow YAML parsed; all six jobs present; `--cov-fail-under=95` still present;
  `compose-browser` step unchanged; `ui/playwright.config.ts` still `retries: 1` in CI.
- Backend gates were not run locally and did not need to be: the branch diff touches only
  `.github/workflows/test.yml` and four `ui/` files. No Python source or test changed.

### Known follow-up, not fixed here (out of scope for this task)

- `ui/test-results/` is not covered by `.gitignore`. Playwright writes traces and screenshots
  there on failure, so a failing local run leaves untracked binary artifacts that can be
  committed by accident. The artifacts generated during this verification were deleted. This gap
  predates the task and was left for a separate change rather than widening scope silently.

## Diff Summary

- Five assigned product/workflow files changed, plus the three required task artifacts.
- No blocked path, dependency manifest, lockfile, Compose file, Dockerfile, or changelog was
  changed.

## Review Focus

`Kimi review of Codex/Luna elevated implementation`

## Agent Ownership Check

- Confirmed repository `W-A-I-T/wait-local-agent` and branch
  `ai/wla-ci-compose-browser-race-green`. All changed paths are within
  `assigned_file_ownership`; no `blocked_paths` were touched. Work remains uncommitted for
  review, with human merge authority preserved.
