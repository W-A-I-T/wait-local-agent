# Implementation

- Added `SmartActionRuns.tsx` with client-scoped GET-only list and detail
  requests, refresh, readable output/evidence, and graceful 404 handling.
- Registered `smart-actions/runs` and added the Smart Action Runs sidebar link.
- Added Vitest coverage for scoped requests, detail rendering, empty state,
  404 handling, and absence of write controls.
- Updated `CHANGELOG.md`.

No catalog, backend, migration, or test-suite files outside `ui/src` were
modified.
