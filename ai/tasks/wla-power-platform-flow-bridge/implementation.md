# Implementation — wla-power-platform-flow-bridge

Status: implemented; awaiting required cross-family review and final gate.

## Diff summary

- `src/wait_local_agent/power_platform_package.py`: Added the bounded nested
  Power Automate action normalizer and rewrote flow emission to require and
  preserve the producer's nested trigger/action payload, validate approval
  flags, and reject the legacy flat shape.
- `tests/test_power_platform_package.py`: Updated the flow fixture to the
  canonical nested shape and added regression, malformed-shape, ordering,
  determinism, optional tool-reference, and approval propagation coverage.
- `ui/src/lib/solutionDeliveryHandoff.ts`: Added the pure router-state handoff
  collector and silent malformed-state reader.
- `ui/src/lib/solutionDeliveryHandoff.test.ts`: Added collector ordering,
  filtering, valid narrowing, and malformed-state tests.
- `ui/src/screens/Consultant.tsx`: Added tenant-guarded, non-submitting handoff
  navigation and the Solution delivery handoff panel.
- `ui/tests/Consultant.test.tsx`: Added end-to-end sender navigation-state and
  pre-artifact disabled-button coverage.
- `ui/src/screens/SolutionDelivery.tsx`: Added one-shot router-state intake,
  lazy package-form prefilling, state clearing, and a status notice while
  preserving the existing package, materialization, approval, and execution
  gates.
- `ui/src/screens/SolutionDelivery.test.tsx`: Added prefill/post-body,
  hand-edit, malformed-state, and materialization-gate coverage; the existing
  local pac CLI assertion was left unchanged.
- `docs/consultant/consultant-power-platform-package.md`: Documented the
  canonical nested flow payload and emitted action metadata.
- `docs/consultant/power-automate-workflows.md`: Documented unchanged plan
  handoff into the source packager.
- `CHANGELOG.md`: Added the breaking flat-shape rejection and the corrected
  flow source/digest entries.
- `ai/tasks/wla-power-platform-flow-bridge/{implementation.md,review.md,status.json}`:
  Updated implementation, review, and orchestration state.

## Deviations

- `python -m pytest --cov=wait_local_agent --cov=packs --cov-report=term-missing --cov-fail-under=95` was not run, per the explicit task environment rule that the orchestrator runs Python verification and pytest hangs in this repository.
- `bandit -r src` was not run because the task environment explicitly limited permitted checks to Ruff, mypy, and UI node/npm commands.
- `python scripts/public_surface_audit.py` was not run for the same permitted-command restriction; the three changed documentation/changelog files were manually checked for all seven forbidden substrings and none matched.
- `npm --prefix ui ci` was not run because `ui/node_modules` was already present and no dependency changed; the existing installation was used for the permitted UI checks.
- The default UI coverage command hit the repository's existing 5-second timeout in four unrelated tests under instrumentation. The same full suite passed with `--testTimeout=30000`; no source or test timeout configuration was changed.

## Gate results

Ruff:

```text
$ ruff check .
All checks passed!
```

Changed-file mypy:

```text
$ mypy tests/test_power_platform_package.py src/wait_local_agent/power_platform_package.py
Success: no issues found in 2 source files
```

Full mypy:

```text
$ mypy src tests
src/wait_local_agent/api/auth_routes.py:12: error: Cannot find implementation or library stub for module named "slowapi"  [import-not-found]
src/wait_local_agent/api/app.py:23: error: Cannot find implementation or library stub for module named "slowapi"  [import-not-found]
src/wait_local_agent/api/app.py:24: error: Cannot find implementation or library stub for module named "slowapi.errors"  [import-not-found]
src/wait_local_agent/api/app.py:24: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
src/wait_local_agent/api/app.py:25: error: Cannot find implementation or library stub for module named "slowapi.extension"  [import-not-found]
src/wait_local_agent/api/app.py:26: error: Cannot find implementation or library stub for module named "slowapi.middleware"  [import-not-found]
src/wait_local_agent/api/app.py:27: error: Cannot find implementation or library stub for module named "slowapi.util"  [import-not-found]
Found 6 errors in 2 files (checked 290 source files)
```

Changed and adjacent UI tests:

```text
$ npm --prefix ui run test -- --run src/lib/solutionDeliveryHandoff.test.ts src/screens/SolutionDelivery.test.tsx ../ui/tests/Consultant.test.tsx
Test Files  3 passed (3)
Tests  21 passed (21)
```

Affected and adjacent UI regression tests:

```text
$ npm --prefix ui run test -- --run src/screens/Consultant.test.tsx src/app/__tests__/Sidebar.test.tsx tests/App.test.tsx
Test Files  3 passed (3)
Tests  32 passed (32)
```

Default UI coverage gate:

```text
$ npm --prefix ui run test:coverage
Test Files  4 failed | 71 passed (75)
Tests  4 failed | 420 passed (424)
Error: Test timed out in 5000ms.
```

UI coverage with the extended timeout required for this repository's
instrumented tests:

```text
$ npm --prefix ui run test:coverage -- --testTimeout=30000
Test Files  75 passed (75)
Tests  424 passed (424)
Statements   : 76.17% ( 5196/6821 )
Branches     : 68.84% ( 4518/6563 )
Functions    : 74.17% ( 1479/1994 )
Lines        : 77.6% ( 4795/6179 )
```

UI build:

```text
$ npm --prefix ui run build
✓ built in 620ms
```

`git diff --check` passed. No Python pytest, Bandit, or deployment operation
was executed.

## Follow-up epic

No new findings belong in the Power Platform Native Builder follow-up epic.
