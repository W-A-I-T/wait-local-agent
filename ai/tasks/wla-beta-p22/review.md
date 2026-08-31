# Review

## Changed Files

- `ui/src/app/ActivityShell.tsx`
- `ui/src/app/AutomationsShell.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/app/__tests__/ActivityRoutes.test.tsx`
- `ui/src/app/__tests__/ActivityShell.test.tsx`
- `ui/src/app/__tests__/AutomationsShell.test.tsx`
- `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/tests/Events.test.tsx`
- `ui/tests/Schedules.test.tsx`

## Risk Areas

- Route composition is the primary risk: all six existing paths must retain their current screen and data behavior while gaining the shared shell.
- The Automations Run description now contains a cross-link to the existing `/executions` route; no route rename or redirect was introduced.
- This packet changes presentation and navigation only. Existing screen-level role gates, API calls, and data boundaries are unchanged.

## Version & Compatibility Evidence

- No version or API changes.
- `npm ci` validated the existing `ui/package-lock.json` versions; the package manifest was not changed. Node `v24.16.0` satisfies the UI engine range.
- No dependency or integration upgrade was warranted for this UI-only route and navigation change.
- Remaining tooling warnings are pre-existing: Vite's future native config-loader warning and the existing large production chunk warning.

## Open Questions

- None.

## Test Results

- Focused ActivityShell, route, AutomationsShell, and Sidebar tests: 28 passed.
- Full `npm test -- --run`: 62 test files and 321 tests passed on run one.
- Full `npm test -- --run`: 62 test files and 321 tests passed on run two.
- `npm run build`: passed, including TypeScript build and Vite production build.
- `git diff --check`: passed.

## Diff Summary

- Adds one shared Activity & scheduling shell with six labeled tabs and descriptions.
- Mounts all six existing activity screens under the shell and keeps their paths stable.
- Consolidates navigation under `Activity` and adds the Run-tab history cross-link.

## Requested Review Focus

- Confirm the six tab paths/descriptions, route wrappers, and the five-entry navigation reduction.
- Confirm no screen data fetching or authorization behavior changed.
