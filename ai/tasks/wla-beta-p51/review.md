# Review

## Changed Files

- `ui/src/app/DashboardContext.tsx`
- `ui/src/app/__tests__/DashboardContext.test.tsx`
- `ui/src/app/__tests__/AppShell.test.tsx`
- Task artifacts under `ai/tasks/wla-beta-p51/`

## Risk Areas

- Auth-state precedence is security-adjacent UI state: demo mode must remain
  more specific than the open-auth flag.
- `canWrite` and `isAdmin` still represent role permission rather than the
  backend write-gate posture; this known mismatch is documented as follow-up.
- Consultant controlled execution remains gated by both `authState ===
  "demo"` and blocked write health, with no change to its request payload or
  backend boundary.

## Version & Compatibility Evidence

- No version or API changes. `npm ci` used the committed lockfile; validation
  ran with Node 24.16.0, Vite 8.2.2, and Vitest 4.1.11. No dependency update
  was needed for this UI-only branch-order fix.
- Remaining tooling warning: Vite reports the repository's existing
  config-loader extension warning; it does not fail tests or the build.

## Open Questions

- Should a follow-up derive write affordances from both role and resolved
  write-health posture, including non-demo local-open installs with the safe
  default `WAIT_ALLOW_WRITE_ACTIONS` setting?

## Test Results

- Targeted UI suites: passed, 29 tests.
- Full UI suite: passed on rerun, 69 files and 360 tests.
- Production build: passed.
- The first full run had one transient suite-level failure in the unrelated
  Launch Passport flow; its isolated test passed and the immediate full rerun
  was fully green.

## Diff Summary

- Demo backend responses now show `Demo mode` and expose the existing
  restriction explanation instead of being mislabeled `Local mode · full
  access`. Non-demo open responses remain `Local mode · full access`.

## Requested Review Focus

- narrow diff review

## Blocker

- 2026-08-31T21:55:52Z: Codex implementation exited with status 143.
- Resolved during this run: no worker process remained; implementation and
  validation completed successfully.
