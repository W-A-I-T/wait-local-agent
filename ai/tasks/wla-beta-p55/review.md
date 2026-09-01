# Review

## Changed Files

- Seven UI screens now use the top-bar client scope for scoped writes.
- Client selector rollout tests and screen-specific request/gating tests were updated.
- Task artifacts were synchronized.

## Risk Areas

- Scheduled freeform JSON can no longer select a different `client_id`; the top-bar selection intentionally wins.
- Consultant blueprint and discovery scopes remain local override/fallback paths by design; the top-bar scope is used when those are absent.
- No backend, authentication, authorization, persistence, migration, dependency, or secret changes were made.

## Version & Compatibility Evidence

- No dependency or API changes were made.
- `npm ci` used the committed `ui/package-lock.json`; `npm ls --depth=0` resolved the declared compatible versions.
- `npm outdated --json` returned no outdated packages.
- Backend request-model/route inspection verified existing `client_id` contracts for all changed requests.

## Open Questions

- None.

## Test Results

- Focused acceptance run: 5 files, 33 tests passed.
- Full `npm test -- --run`: 71 files, 397 tests passed twice.
- `npm run build`: passed.
- `git diff --check`: passed.
- Existing warnings remain: Vite native config-loader extension warning and a large minified chunk warning.

## Diff Summary

- Scoped actions now stop with clear client-selection copy instead of sending empty tenant scope. Request bodies carry the current top-bar client, scheduled params are normalized from the selector, and Agents/Consultant preserve their documented local override behavior.

## Requested Review Focus

- Confirm no scoped action still uses the auth-derived `clientId` where `selectedClientId` is required, and confirm no-client gates remain limited to the actions whose backend contracts require a client.
