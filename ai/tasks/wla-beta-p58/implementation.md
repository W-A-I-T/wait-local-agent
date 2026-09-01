# Implementation Notes

## Summary

- Added an active-only Demo mode explanation below the Admin Settings status table.
- Added dedicated `Settings` screen tests for active and inactive demo mode, including all requests made by `refresh()`.
- Retained the existing Demo mode enabled/disabled row for at-a-glance status; the subsection adds the missing operational context without introducing a control.
- Copy is limited to the verified demo-mode restrictions (write actions and Power Platform deployment), separately configured `WAIT_ALLOW_*` restrictions, and the startup/restart mechanism for `WAIT_DEMO_MODE`.
- No backend, API, dependency, or model/lane-reporting changes were made.

## Commands Run

- `pwd && git remote -v && git status --short --branch` — verified `/home/josephp/wla-beta-p58`, `W-A-I-T/wait-local-agent`, and branch `ai/wla-beta-p58-settings-honesty` based on `origin/main`.
- `rg 'allow_write_actions|allow_power_platform_deployment' src/wait_local_agent/api/app.py` — confirmed demo startup overrides write actions and Power Platform deployment, with no new UI/API field needed.
- `rg 'frozen=True' -A2 src/wait_local_agent/config.py` — confirmed `Settings` is frozen and startup-loaded.
- `npm ci` in `ui` — installed the existing lockfile toolchain; audit reported 0 vulnerabilities.
- `npm test -- --run src/screens/Settings.test.tsx` — passed: 1 test file, 2 tests.
- Final `npm test -- --run` — passed: 70 test files, 362 tests.
- Final repeated `npm test -- --run` — passed: 70 test files, 362 tests.
- `npm test -- --run src/app/__tests__/Sidebar.test.tsx` — passed: 1 test file, 10 tests after an unrelated full-suite timeout.
- `npm run build` — passed: TypeScript compilation and Vite production build (Vite 8.2.2).
- `git diff HEAD --check` — passed.
- The test runs and build emitted the existing Vite `configLoader: 'native'` future-warning; the build also emitted the existing large-chunk warning.
- Two earlier full-suite attempts had unrelated loading/timeouts outside the changed files; the two final full-suite attempts were green.

## Files Touched

- `ui/src/screens/Settings.tsx`
- `ui/src/screens/Settings.test.tsx`
- `ai/tasks/wla-beta-p58/implementation.md`
- `ai/tasks/wla-beta-p58/review.md`
- `ai/tasks/wla-beta-p58/status.json`

## Follow-Up

- The required read-only Kimi cross-family review was attempted through `wait-harness --run review wla-beta-p58`, but the provider returned HTTP 500 after retrying; retry when the provider is available. Human retains merge authority.
