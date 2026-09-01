# Review

## Changed Files

- `ui/src/screens/Settings.tsx` — active-only Demo mode explanation using existing styles.
- `ui/src/screens/Settings.test.tsx` — isolated active/inactive rendering coverage with all `Settings.refresh()` requests mocked.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- The explanation renders only when the existing `security.demo_mode` boolean is true; it introduces no new fetch, state mutation, or API contract.
- The copy is intentionally static because `/settings/security` does not expose individual write/deployment gate values.
- No secrets, auth, authorization, persistence, migration, or dependency surface was changed.
- The dedicated test preserves the real `ApiRequestError` export while mocking only `apiFetch`, so existing error handling remains intact.

## Version & Compatibility Evidence

- No dependency or API changes were made. `npm ci` used the committed `ui/package-lock.json`; the existing Vite 8.2.2 toolchain built successfully.

## Open Questions

- None for the implementation scope. The reciprocal Kimi review was attempted with the canonical harness but returned a provider HTTP 500 after retrying, so no independent Kimi verdict is available yet.

## Test Results

- `cd ui && npm test -- --run src/screens/Settings.test.tsx` — passed, 1 file / 2 tests.
- Final `cd ui && npm test -- --run` — passed, 70 files / 362 tests.
- Final repeated `cd ui && npm test -- --run` — passed, 70 files / 362 tests.
- `cd ui && npm test -- --run src/app/__tests__/Sidebar.test.tsx` — passed, 1 file / 10 tests after an unrelated full-suite timeout.
- `cd ui && npm run build` — passed.
- `git diff HEAD --check` — passed.
- Two earlier full-suite attempts had unrelated loading/timeouts outside the changed files; the two final full-suite attempts were green.
- Existing Vite config and chunk-size warnings remain non-blocking.

## Diff Summary

- Admin Settings still shows the current Demo mode status row. When demo mode is active, it now explains the two verified restrictions, distinguishes independent `WAIT_ALLOW_*` configuration, and states that changing `WAIT_DEMO_MODE` requires editing appliance environment configuration and restarting the appliance. When inactive, the explanatory subsection is omitted.

## Requested Review Focus

- Confirm the copy remains limited to verified demo-mode behavior and that no implied live toggle or unverified per-gate status is introduced.
- Confirm the dedicated active/inactive tests cover the acceptance boundary without changing unrelated Settings rendering.

## Blocker

- Kimi cross-family review remains pending because the canonical provider attempt exited with status 1 after an HTTP 500; retry when the provider is available.
