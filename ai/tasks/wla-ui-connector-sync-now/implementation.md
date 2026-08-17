# Implementation — wla-ui-connector-sync-now

Implemented the admin-only Connector Instances "Sync now" action. Selecting
an instance exposes a per-instance button that POSTs to the existing sync
endpoint, disables while busy, and renders the returned status, counts, page
count, and reason inline. `skipped_locked` is rendered as a normal summary
status. 404 and 409 failures remain inline notices; 409 notices use only the
safe backend reason and never expose technical details or credentials.

## Files changed

- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/api/types.ts`
- `ui/src/screens/__tests__/ConnectorInstances.test.tsx`
- `CHANGELOG.md`
- `ai/tasks/wla-ui-connector-sync-now/status.json`
- `ai/tasks/wla-ui-connector-sync-now/implementation.md`
- `ai/tasks/wla-ui-connector-sync-now/review.md`

No files under `src/wait_local_agent/` or the repository `tests/` directory
were changed. No commit or push was made.

## Validation

`cd ui && npm test -- --run`:

```text
Test Files  38 passed (38)
Tests  163 passed (163)
```

`cd ui && npm run build` completed successfully. Vite emitted its existing
non-failing warning that some chunks exceed 500 kB after minification.

Claude final gate remains the merge authority.
