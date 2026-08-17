# Implementation

Task: `wla-ui-clients-selector`

## Scope

- Added the read-only Clients directory at `/clients`, with loading, empty,
  retryable error, active/archived status, and reserved `__quarantine__`
  filtering behavior.
- Added a separate `selectedClientId` field to `DashboardContext`, defaulting
  to `""` for All clients, plus the `/clients` options loaded during the
  existing dashboard refresh.
- Added the ungated sidebar entry, flat route, and accessible app-shell select.
- Promoted `ClientDirectoryEntry` into the shared API types and reused it in
  Sync / Reconciliation without changing that screen's behavior.
- Added focused Clients and DashboardContext coverage. No existing screen was
  rewired to consume the DashboardContext `selectedClientId`.

No files under `src/` were changed. No commit or push was performed.

## Security and scope review

- The directory uses the existing viewer-readable `GET /clients` endpoint and
  exposes only client name, ID, and status.
- The reserved `__quarantine__` entry is excluded from both directory rows and
  selector options. Only active clients appear in the selector.
- The existing `clientId` context field and its `/auth/role` source remain
  unchanged; no existing screen requests now include the new selector field.

## Validation

Exact command results:

```text
$ cd ui && npm test

> wait-local-agent-ui@1.1.1 test
> vitest run

 RUN  v4.1.10 /home/josephp/wla-apr1/ui

 Test Files  35 passed (35)
      Tests  149 passed (149)
   Duration  15.02s

$ cd ui && npm run build

> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
✓ 1867 modules transformed.
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-BtMBc2zC.css   35.43 kB │ gzip:   6.63 kB
dist/assets/index-V-UX-W9p.js   539.23 kB │ gzip: 144.78 kB
(!) Some chunks are larger than 500 kB after minification.
✓ built in 4.24s
```
