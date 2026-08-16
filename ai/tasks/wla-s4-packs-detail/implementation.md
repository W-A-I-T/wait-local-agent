# Implementation

## Summary

Implemented the UI-only, read-only System → Extensions / Packs surface. It
loads the existing `GET /packs` summary list and `GET /packs/status` detail
list, then shows each pack's version, lock/trust state, license requirement,
CLI/router availability, mount state, and reported error. The screen is
admin-gated in the System navigation and does not call `POST /packs/install`.

## Files touched

- `ui/src/api/types.ts`
- `ui/src/screens/ExtensionsPacks.tsx`
- `ui/src/routes.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/styles.css`
- `ui/tests/ExtensionsPacks.test.tsx`
- `docs/ai-workflow/surface-coverage.json`
- `CHANGELOG.md`
- `ai/tasks/wla-s4-packs-detail/implementation.md`

No files under `src/` were changed. No commit or push was performed.

## Security and scope review

- The page is read-only and uses only the two existing viewer-readable GET
  endpoints requested by the task.
- The screen and its System navigation entry are gated with the shared
  `RoleGate` and `allowed={["admin"]}`.
- No install, write, secret, or provider/deployment behavior was added.
- The status detail renders only the fields returned by the existing route:
  `cli_available`, `router_available`, `mounted_cli`, `mounted_router`, and
  `error`, alongside the pack summary fields.

## Validation

Dependencies were already installed. Exact command results from this checkout:

```text
cd ui && npm test

> wait-local-agent-ui@1.1.1 test
> vitest run

 RUN  v4.1.10 /home/josephp/wla-ui-packs/ui

 Test Files  29 passed (29)
      Tests  121 passed (121)
   Start at 23:01:32
   Duration 6.67s (transform 5.85s, setup 3.55s, import 11.42s, tests 32.30s, environment 33.09s)

cd ui && npm run build

> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
transforming...
✓ 1861 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-JUYad1qe.css   26.98 kB │ gzip:   5.63 kB
dist/assets/index-qkg6HkiX.js   493.70 kB │ gzip: 136.87 kB
✓ built in 5.11s
```
