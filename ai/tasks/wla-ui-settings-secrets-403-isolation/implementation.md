# Implementation Notes

## Summary

- Isolated the `GET /secrets` load inside the existing concurrent `Promise.all`
  using the same typed `.then(success, error)` pattern already used for Launch
  Passport status.
- Successful settings loads now commit provider, security, pack, and update
  data even when demo mode returns 403 for `/secrets`.
- Added explicit Vault messaging for demo-mode unavailability and generic
  secret-load failures. The 403 classifier requires both `ApiRequestError` and
  `security.demo_mode === true`; other settings 403 responses still reach the
  existing administrator-role error path.
- No backend, dependency, API, secret-value, or credential-display changes.

## Commands Run

- `npm test -- --run src/screens/Settings.test.tsx --configLoader runner` —
  3 tests passed.
- `npm test -- --run tests/wla-wp17.test.tsx tests/wla04-surfaces.test.tsx
  --configLoader runner --no-file-parallelism` — 23 tests passed.
- `npm run build -- --configLoader runner` — passed with the existing Vite
  large-chunk warning.
- Full UI suite with Vitest 4.1.11 and `--no-file-parallelism` — 362 tests
  passed and 1 unrelated, order-sensitive `wla-wp17` test failed. That test
  passes when run in isolation; no FounderJourney files were changed.
- `git diff --check` — passed.

The checkout did not contain `ui/node_modules`. Validation used a temporary
symlink to the existing compatible WLA dependency tree; the symlink was
removed afterward and no dependency files were changed.

## Files Touched

- `ui/src/screens/Settings.tsx`
- `ui/src/screens/Settings.test.tsx`
- `ai/tasks/wla-ui-settings-secrets-403-isolation/implementation.md`
- `ai/tasks/wla-ui-settings-secrets-403-isolation/review.md`
- `ai/tasks/wla-ui-settings-secrets-403-isolation/status.json`

## Follow-Up

- Kimi cross-family read-only review remains the next workflow action.
- Investigate the unrelated order-sensitive `wla-wp17` failure if a fully green
  repository-wide run is required.
