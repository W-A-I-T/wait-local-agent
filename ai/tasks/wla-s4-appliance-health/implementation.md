# Implementation Notes

## Summary

Implemented the UI-only admin System → Appliance Health surface. The page is
read-only and aggregates the verified `GET /health`, `GET /update-status`, and
`GET /hardening/runs` contracts, including appliance flags, configured
connectors, update status, and the latest hardening run. It is gated until the
dashboard resolves an administrator role, and the sidebar entry is hidden for
non-admins.

The surface-coverage manifest already classified all three GET routes as
`exposed` on this branch, so no semantic documentation change was needed.

## Commands Run

- `cd ui && npm ci` — passed; 160 packages installed, 0 vulnerabilities.
- `cd ui && npm test` — passed; 27 test files and 115 tests.
- `cd ui && npm run build` — passed; TypeScript and Vite production build.
- `git diff --check` — passed.

## Files Touched

- `ui/src/screens/ApplianceHealth.tsx`
- `ui/src/routes.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/api/types.ts`
- `ui/src/styles.css`
- `ui/tests/ApplianceHealth.test.tsx`
- `CHANGELOG.md`
- `ai/tasks/wla-s4-appliance-health/implementation.md`
- `ai/tasks/wla-s4-appliance-health/review.md`
- `ai/tasks/wla-s4-appliance-health/status.json`

## Follow-Up

Obtain the required cross-family review and Claude final gate before merge.
No backend files were changed, and the manifest already had the requested
route classifications.
