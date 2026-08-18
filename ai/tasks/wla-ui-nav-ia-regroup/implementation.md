# Implementation: Sidebar IA regroup

## Scope

- Reorganized `ui/src/app/Sidebar.tsx` into the exact product groups from the
  plan without changing any route path.
- Kept Playbooks first in Automations and moved low-frequency surfaces into a
  native, collapsed-by-default `details` drawer labeled System / Advanced.
- Preserved the existing admin `RoleGate` wrappers for Connector Instances,
  Sync / Reconciliation, Appliance Health, Extensions / Packs, and MCP.
- Renamed only the Consultant label to Solutions Architect; its destination is
  still `/consultant`.
- Added focused Sidebar Vitest coverage and minimal native-details styling.

## Files changed

- `ui/src/app/Sidebar.tsx`
- `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/src/styles.css`
- `CHANGELOG.md`
- `ai/tasks/wla-ui-nav-ia-regroup/implementation.md`
- `ai/tasks/wla-ui-nav-ia-regroup/review.md`
- `ai/tasks/wla-ui-nav-ia-regroup/status.json`

No routes, screens, `src/wait_local_agent/`, or `tests/` files were changed.

## Validation

From `ui/`:

```text
$ npm test -- --run
Test Files  44 passed (44)
     Tests  191 passed (191)
Start at  22:18:46
Duration  18.39s (transform 12.11s, setup 10.39s, import 28.97s, tests 101.23s, environment 98.44s)

$ npm run build
vite v6.4.3 building for production...
✓ 1870 modules transformed.
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-Dm4Q9ksu.css   35.68 kB │ gzip:   6.68 kB
dist/assets/index-BtjXmL0N.js   573.31 kB │ gzip: 153.00 kB
✓ built in 3.91s
```

The build emitted the existing non-blocking warning that some chunks exceed
500 kB after minification.
