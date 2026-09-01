# Review

## Changed Files

- `ui/src/screens/Settings.tsx` — active-only Demo mode explanation using existing styles.
- `ui/tests/wla04-surfaces.test.tsx` — active/inactive demo-mode acceptance coverage.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- The explanation renders only when the existing `security.demo_mode` boolean is true; it introduces no new fetch, state mutation, or API contract.
- The copy is intentionally static because `/settings/security` does not expose individual write/deployment gate values.
- No secrets, auth, authorization, persistence, migration, or dependency surface was changed.

## Version & Compatibility Evidence

- No dependency or API changes were made. `npm ci` used the committed `ui/package-lock.json`; the existing Vite 8.2.2 toolchain built successfully.

## Open Questions

- None for the implementation scope.

## Test Results

- `cd ui && npm test -- --run tests/wla04-surfaces.test.tsx` — passed, 1 file / 8 tests.
- `cd ui && npm test -- --run` — passed, 69 files / 361 tests.
- Repeated `cd ui && npm test -- --run` — passed, 69 files / 361 tests.
- `cd ui && npm run build` — passed.
- `git diff --check` — passed.
- Existing Vite config and chunk-size warnings remain non-blocking.

## Diff Summary

- Admin Settings still shows the current Demo mode status row. When demo mode is active, it now explains the two verified restrictions, distinguishes independent `WAIT_ALLOW_*` configuration, and states that changing `WAIT_DEMO_MODE` requires editing appliance environment configuration and restarting the appliance. When inactive, the explanatory subsection is omitted.

## Requested Review Focus

- Confirm the copy remains limited to verified demo-mode behavior and that no implied live toggle or unverified per-gate status is introduced.
- Confirm the new active/inactive assertions cover the acceptance boundary without changing unrelated Settings assertions.

## Blocker

- 2026-09-01T00:55:31Z: Kimi cross-family review exited with status 1.
