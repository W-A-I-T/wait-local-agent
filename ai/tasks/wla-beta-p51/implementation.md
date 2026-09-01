# Implementation Notes

## Summary

- Fixed `deriveAuthState` so `demo_mode` takes precedence over
  `api_auth_required === false`. This makes the real backend demo response
  resolve to `"demo"` while preserving `"local-open"` for a non-demo open
  install.
- Kept the existing AppShell demo explanation and Consultant controlled-mode
  gate unchanged; the existing Consultant coverage now exercises the reachable
  demo + Safe Mode path.
- Investigated `canWrite` and `isAdmin`: they remain `true` in demo mode
  because the backend resolves demo access as `role: "admin"` and the current
  context formulas allow any non-viewer role. The branch-order fix therefore
  does not correct the separate UI write-capability mismatch; backend demo
  write/deployment gates still reject those operations. The same issue likely
  exists for a fresh non-demo local-open install when
  `WAIT_ALLOW_WRITE_ACTIONS` is unset. This is follow-up work and was not
  changed in this UI-only packet.

## Commands Run

- `npm ci` in `ui` — passed; installed the existing lockfile, audit found 0
  vulnerabilities.
- `npm test -- --run src/app/__tests__/DashboardContext.test.tsx src/app/__tests__/AppShell.test.tsx src/screens/Consultant.test.tsx` — passed;
  3 files, 29 tests.
- `npm test -- --run` — first run had 359/360 tests pass with one suite-level
  failure in `tests/wla-wp17.test.tsx`; the failing test passed in isolation.
- `npm test -- --run` — passed on the required rerun; 69 files, 360 tests.
- `npm run build` — passed; Vite production build completed.
- `git diff --check` — passed.

## Files Touched

- `ui/src/app/DashboardContext.tsx`
- `ui/src/app/__tests__/DashboardContext.test.tsx`
- `ui/src/app/__tests__/AppShell.test.tsx`
- `ai/tasks/wla-beta-p51/implementation.md`
- `ai/tasks/wla-beta-p51/review.md`
- `ai/tasks/wla-beta-p51/status.json`

## Follow-Up

- Reconcile UI `canWrite`/`isAdmin` with effective backend write posture so
  demo mode and safe local-open mode do not render write actions as available
  when the backend will block them. Keep role permission and write-gate
  readiness as separate concepts.
