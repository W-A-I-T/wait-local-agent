# Review

## Changed Files

- `ui/src/api/types.ts`
- `ui/src/app/AppShell.tsx`
- `ui/src/app/DashboardContext.tsx`
- `ui/src/app/__tests__/DashboardContext.test.tsx`
- `ui/src/screens/Settings.tsx`
- `ui/src/styles.css`
- `ui/tests/App.test.tsx`
- `ui/tests/wla-wp17.test.tsx`

## Risk Areas

- Auth-state precedence is intentionally `local-open` when
  `api_auth_required === false`, then `demo` when `demo_mode === true`, then
  `authenticated` only when a stored token exists and the role resolves.
- A 401 is classified as `invalid-token` only when a stored token exists;
  credential values are not included in status messages, popovers, or logs.
- Local-open changes only client-side capability presentation to match the
  server contract that all requests run as admin in that mode.
- `AuthRoleResponse` accepts the existing optional `is_msp_admin` and
  `principal_id` fields without adding a request or changing server behavior.

## Version & Compatibility Evidence

- No version or API changes. The implementation uses the existing `/auth/role`
  contract and committed `ui/package-lock.json`; `npm ci` installed the
  lockfile versions (`vitest 4.1.11`, `vite 8.2.2`) without modifying package
  declarations or the lockfile. No newer dependency was needed or introduced,
  so there is no dependency migration risk from this task.

## Open Questions

- Confirm the intended product precedence if a future server response sets
  both `api_auth_required: false` and `demo_mode: true`; this implementation
  follows the plan’s local-open definition first.

## Test Results

- `cd ui && npm test -- --run`: 55 files and 272 tests passed.
- `cd ui && npm run build`: passed.
- `git diff --check`: passed.
- Existing warnings: Vite extensionless config import and large minified
  chunk; both predate this change.

## Diff Summary

- Shared auth context now distinguishes open, demo, authenticated, and
  rejected-token sessions. The top bar and Settings screen consume that same
  state, explain token setup without exposing secrets, and provide immediate
  save feedback.

## Requested Review Focus

- Verify auth-state precedence, 401 handling, local-open admin gating, and
  that no token value enters rendered text or logs.
