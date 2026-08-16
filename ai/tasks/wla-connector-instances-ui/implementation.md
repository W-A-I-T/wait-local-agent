# Implementation

Implemented the read-only admin Connector Instances screen under Integrations.

## Scope

- Added `ui/src/screens/ConnectorInstances.tsx` using only
  `GET /connector-instances` and
  `GET /client-connector-mappings?connector_instance_id=...`.
- Rendered the real connector instance fields for display name, type, status,
  owning client, and credential presence. Credential references and connector
  configuration are never rendered.
- Added selectable instances with external-company to WAIT-client mappings and
  explicit Verified / Unverified badges.
- Added loading, empty, retryable error, and administrator access states using
  the existing screen and `RoleGate` patterns.
- Added the `integrations/connector-instances` route, one admin-gated sidebar
  entry, API response types, focused styles, and UI tests.
- The existing surface manifest already classifies the three P1 GET routes as
  `admin`; its runtime schema has no UI-route section, so no classification was
  duplicated or changed.

No files under `src/` were changed. No mutation endpoint is wired. No commit or
push was performed.

## Security and scope review

- The screen is admin-gated before any connector-estate request is made.
- `credential_ref` and `config_json` are used only for safe presence/rendering
  decisions and are not included in rendered text, attributes, or details.
- The only requests made by the screen are GET requests; no create, verify,
  update, or other mutation action is available.

## Validation

Exact requested command results:

```text
$ cd ui && npm test

> wait-local-agent-ui@1.1.1 test
> vitest run

 RUN  v4.1.10 /home/josephp/wla-ui-conn/ui

 Test Files  33 passed (33)
      Tests  130 passed (130)
   Start at 03:21:33
   Duration 6.60s (transform 4.49s, setup 3.67s, import 10.66s, tests 33.79s, environment 33.36s)

$ cd ui && npm run build

> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
✓ 1865 modules transformed.
dist/index.html 0.47 kB │ gzip: 0.30 kB
dist/assets/index-CnuKfqun.css 33.60 kB │ gzip: 6.43 kB
dist/assets/index-CrdsuDUp.js 521.09 kB │ gzip: 141.74 kB
✓ built in 2.12s
```

The build also emitted Vite's non-failing warning that a JavaScript chunk is
larger than 500 kB after minification.

## Files changed

- `CHANGELOG.md`
- `ui/src/api/types.ts`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/styles.css`
- `ui/tests/ConnectorInstances.test.tsx`
- `ai/tasks/wla-connector-instances-ui/implementation.md`
