# Implementation Notes

## Summary

- Added `ActivityShell` with the shared AutomationsShell structure, six stable-route tabs, and the plan's per-tab descriptions.
- Wrapped Events, Schedules, Scheduled Jobs, Smart Action Runs, Executions, and Backfills in the new shell without changing their data views or fetch paths.
- Renamed Control's `/executions` navigation entry to `Activity`, removed the duplicate schedule/activity links, and linked the Automations Run description to `Run history → Activity`.
- Reused the existing `automations-*` classes so Activity follows the established shell styling exactly.

## Navigation Before / After

- Before: Control had `Executions` → `/executions`; Workspace had `Schedules` → `/automation/schedules`; System / Advanced had `Events`, `Scheduled Jobs`, `Smart Action Runs`, and `Backfills`.
- After: Control has `Activity` → `/executions`; Workspace has no schedule entry; System / Advanced has none of those five activity entries. All six remain reachable through the Activity tabs.
- Net navigation reduction: five entries, with the existing `/executions` destination retained under the clearer `Activity` label.

## Commands Run

- `npm ci` in `ui`: completed; installed the existing lockfile versions and reported 0 vulnerabilities.
- Focused shell/route/sidebar tests: 28 passed.
- `npm test -- --run` in `ui`: passed twice, 62 test files and 321 tests each run.
- `npm run build` in `ui`: passed (`tsc -b` and Vite production build).
- `git diff --check`: passed.

## Files Touched

- `ui/src/app/ActivityShell.tsx`
- `ui/src/app/AutomationsShell.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/app/__tests__/ActivityRoutes.test.tsx`
- `ui/src/app/__tests__/ActivityShell.test.tsx`
- `ui/src/app/__tests__/AutomationsShell.test.tsx`
- `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/src/routes.tsx`
- `ui/tests/Events.test.tsx`
- `ui/tests/Schedules.test.tsx`
- `ai/tasks/wla-beta-p22/implementation.md`
- `ai/tasks/wla-beta-p22/review.md`
- `ai/tasks/wla-beta-p22/status.json`

## Follow-Up

- No follow-up implementation was identified. The pre-existing Vite config-loader and large-chunk warnings remain outside this UI-only task.
