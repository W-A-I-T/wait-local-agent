# Implementation

Implemented the admin Operations → Sync / Reconciliation Center as a UI-only
slice over the existing ingestion endpoints.

## Scope

- Added `ui/src/screens/SyncReconciliation.tsx` with:
  - sync health rows from `GET /ingestion/sync-cursors`;
  - connector display-name/type mapping from `GET /connector-instances`, with
    connector-ID fallback;
  - quarantine rows from `GET /ingestion/unmapped`;
  - plain-labeled cursor values and payload digests;
  - loading, empty, error, success, and retry states;
  - an inline confirm dialog with the exact prompt “Mark this record as
    reviewed?”;
  - the sole mutation, `POST /ingestion/unmapped/{record_id}/resolve`,
    followed by a refetch. Resolved records are filtered from the active
    quarantine list after the refetch.
- Added the `operations/reconciliation` route and one admin-only Sidebar entry.
- Added `SyncCursor` and `UnmappedRecord` API types and screen styles.
- Added focused tests for data rendering, all cursor statuses, connector
  fallback, confirm-gated resolution/refetch, resolve errors, empty/error
  states, and viewer access gating.
- Added the Unreleased changelog entry.

The existing surface manifest already classifies `GET /connector-instances`,
`GET /ingestion/sync-cursors`, `GET /ingestion/unmapped`, and
`POST /ingestion/unmapped/{record_id}/resolve` as `admin`; its generated
inventory shape was preserved. No UI-only manifest key was added.

No files under `src/` were changed. No sync-now, retry, or other mutation was
wired. No commit or push was performed, and no PR was created because the user
explicitly requested local implementation only.

## Validation

Exact requested commands:

```text
$ cd ui && npm test
> wait-local-agent-ui@1.1.1 test
> vitest run

 RUN  v4.1.10 /home/josephp/wla-ui-sync/ui

 Test Files  34 passed (34)
      Tests  135 passed (135)
   Start at  04:11:29
   Duration  11.08s (transform 5.41s, setup 6.73s, import 15.34s, tests 55.78s, environment 55.97s)
```

```text
$ cd ui && npm run build
> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
transforming...
✓ 1866 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-B6wQYq5a.css   34.59 kB │ gzip:   6.54 kB
dist/assets/index-BWtWPy3c.js   528.19 kB │ gzip: 142.90 kB

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#manual-chunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 2.36s
```

Both commands exited with code 0. The build warning is non-failing and reports
the existing single JavaScript chunk size.

## Files changed

- `CHANGELOG.md`
- `ui/src/api/types.ts`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/screens/SyncReconciliation.tsx`
- `ui/src/styles.css`
- `ui/tests/SyncReconciliation.test.tsx`
- `ai/tasks/wla-sync-reconciliation-ui/implementation.md`
