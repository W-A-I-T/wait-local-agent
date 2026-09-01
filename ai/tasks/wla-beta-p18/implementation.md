# Implementation Notes

## Summary

- Unknown routes now render a lazy `NotFound` panel with the attempted path and
  a link back to Overview.
- `/microsoft-admin/azure-lighthouse` is a lazy route protected by the same
  `MicrosoftAdminCapabilityGate` as `/microsoft-admin`.
- Azure Lighthouse is listed in the Solutions group and uses Microsoft Admin
  pack navigation visibility.
- `useMicrosoftAdminAccess` now exposes `navAllowed` for any active
  `microsoft_admin` grant while preserving `allowed` as the exact selected
  client/global route check. This keeps the pack visible under All clients
  without weakening route-level authorization.

## Commands Run

- `cd ui && npm ci` — passed; installed the checked-in lockfile dependencies,
  no vulnerabilities reported.
- `cd ui && npm test -- --run` — the default unrestricted-parallel run hit the
  existing Sidebar test's 5-second timeout under local resource contention
  (55/56 files completed, 270/271 tests reached).
- `cd ui && npm test -- --run --maxWorkers=2` — passed; 56 test files and 271
  tests.
- `cd ui && npm run build` — passed; TypeScript and Vite production build
  completed, including separate NotFound and Azure Lighthouse chunks.
- `git diff --check` — passed.

## Files Touched

- `ui/src/routes.tsx`
- `ui/src/routes.test.tsx`
- `ui/src/screens/NotFound.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/src/hooks/useMicrosoftAdminAccess.ts`
- `ui/src/hooks/useMicrosoftAdminAccess.test.tsx`
- `ui/src/components/MicrosoftAdminCapabilityGate.test.tsx`
- `ai/tasks/wla-beta-p18/implementation.md`
- `ai/tasks/wla-beta-p18/review.md`
- `ai/tasks/wla-beta-p18/status.json`

## Follow-Up

- The existing Vite config-loader warning about the extensionless
  `apiProxyRoutes` import remains unrelated to this UI-only change.
- No dependency, public API, or backend changes were made; the checked-in
  React Router/Vite/Vitest versions remain the compatible project versions.
