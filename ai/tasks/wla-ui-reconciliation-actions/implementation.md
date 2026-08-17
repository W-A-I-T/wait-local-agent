# Implementation — `wla-ui-reconciliation-actions`

Implemented the Slice-0 operator actions in the existing admin-gated
Operations → Sync / Reconciliation Center.

## Scope

- Added pending-mapping verification with the existing inline confirmation
  dialog pattern. Successful verification refetches the screen and surfaces
  the API `retenanted_count`.
- Added an instance-scoped quarantined-ticket panel with connector selection,
  loading, prompt, empty, retryable error, and danger states.
- Added active-client-only reclassification with a confirmation dialog and a
  JSON `client_id` POST body. Successful reclassification refetches the
  selected connector's quarantine list.
- Added the required API types and Vite proxy route prefixes.
- Extended the focused screen tests for verification, reclassification,
  refetch behavior, 409/400 danger notices, empty states, and viewer denial.

## Boundary and security review

- The existing `RoleGate allowed={["admin"]}` remains unchanged; viewers make
  no requests and do not see the operator panels.
- Only the verified contract endpoints are called. Connector and ticket IDs
  are URI-encoded, reclassification sends the selected client ID as JSON, and
  inactive or `__quarantine__` clients are excluded from the picker.
- No files under `src/` were changed. The surface manifest already classifies
  the relevant backend routes as `admin` and has no UI-surface classification
  section, so no unsupported manifest key was added.
- No commit or push was performed and no PR was created, as requested.

## Validation

Required commands passed from `ui/` after `npm install`:

- `npm test`: 34 test files, 145 tests passed.
- `npm run build`: `tsc -b && vite build` passed. Vite emitted its existing
  non-failing warning about a JavaScript chunk larger than 500 kB.
