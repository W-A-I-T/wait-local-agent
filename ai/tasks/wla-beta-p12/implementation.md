# Implementation Notes

## Summary

- Added one derived `authState` to `DashboardContext` from the existing
  `/auth/role` payload and the presence of the stored token. The state is
  `local-open`, `demo`, `authenticated`, or `invalid-token` (`null` while
  access is unresolved or the server reports authenticated access without a
  stored token).
- Local-open now exposes the existing admin/write UI after access resolves;
  no server authorization, token persistence, header injection, or endpoint
  behavior changed.
- AppShell labels the token field as `API token (optional in local mode)` and
  shows a state chip plus credential-safe explanatory popover. Only
  environment variable names are shown; token values are never copied into
  UI copy or logs.
- Saving a token persists it through the existing helper, refreshes
  `/auth/role`, and reports the resolved role or a rejected-token warning.
- Settings consumes the same context state, treats local-open as full access,
  and names the required administrator role for insufficient-role cases.

## Commands Run

- `npm ci` (from `ui/`) — installed the committed lockfile dependencies; audit
  reported 0 vulnerabilities.
- `cd ui && npm test -- --run src/app/__tests__/DashboardContext.test.tsx tests/App.test.tsx tests/wla-wp17.test.tsx` — 3 files, 33 tests passed.
- `cd ui && npm test -- --run` — 55 files, 272 tests passed.
- `cd ui && npm run build` — TypeScript and Vite production build passed.
- `git diff --check` — passed.
- Vite retains pre-existing warnings about the extensionless config import and
  the large JavaScript chunk; neither is caused by this task.

## Files Touched

- `ui/src/api/types.ts`
- `ui/src/app/AppShell.tsx`
- `ui/src/app/DashboardContext.tsx`
- `ui/src/app/__tests__/DashboardContext.test.tsx`
- `ui/src/screens/Settings.tsx`
- `ui/src/styles.css`
- `ui/tests/App.test.tsx`
- `ui/tests/wla-wp17.test.tsx`

## Follow-Up

- Read-only Kimi review and Claude final gate remain in the handoff workflow.
- The existing Vite config-loader and chunk-size warnings remain for a
  separate maintenance task.
