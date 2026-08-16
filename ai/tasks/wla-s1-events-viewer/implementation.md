# Implementation

Implemented the read-only Events screen under Automation.

## Scope

- Added `ui/src/screens/Events.tsx` with GET-only loading for:
  - `/automation/event-deliveries`
  - `/automation/event-deliveries/{id}`
  - `/event-history`
- Added delivery status badges, verified delivery fields, GET-backed detail, and chronological history rendering.
- Added the `automation/events` route and one viewer-visible Events sidebar entry.
- Added supporting API response types and Events-specific styles.
- Classified the three GET routes as `embedded` in `docs/ai-workflow/surface-coverage.json` and documented the screen in `CHANGELOG.md`.
- Added `ui/tests/Events.test.tsx` covering rendering, list loads, status badges, detail opening, viewer navigation, GET-only behavior, and error state.

No retry or other mutation endpoint is wired by this screen. No files under `src/` were changed.

## Validation

Run after implementation:

```text
$ cd ui && npm test
> wait-local-agent-ui@1.1.1 test
> vitest run

Test Files  31 passed (31)
Tests       125 passed (125)
Start at    23:42:47
Duration    6.28s (transform 4.10s, setup 3.49s, import 10.22s, tests 31.72s, environment 32.77s)
```

```text
$ cd ui && npm run build
> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
✓ 1863 modules transformed.
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-kYBYIHRL.css   30.66 kB │ gzip:   6.11 kB
dist/assets/index-DTTIe_iQ.js   508.06 kB │ gzip: 139.46 kB
✓ built in 2.04s
```

The build also emitted Vite's non-failing warning that the JavaScript chunk is larger than 500 kB.

## Files changed

- `CHANGELOG.md`
- `docs/ai-workflow/surface-coverage.json`
- `ui/src/api/types.ts`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/screens/Events.tsx`
- `ui/src/styles.css`
- `ui/tests/Events.test.tsx`
- `ai/tasks/wla-s1-events-viewer/implementation.md`
