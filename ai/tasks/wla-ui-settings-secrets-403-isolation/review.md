# Review

## Changed Files

- `ui/src/screens/Settings.tsx`
- `ui/src/screens/Settings.test.tsx`
- Task artifacts under `ai/tasks/wla-ui-settings-secrets-403-isolation/`

## Risk Areas

- The isolated result must classify only demo-mode `/secrets` 403 responses as
  the expected restriction; genuine provider/security permission failures must
  continue to reject `Promise.all` and show the existing role-required message.
- The Vault panel clears the secret list on any isolated failure and shows a
  bounded status message without rendering API error details or secret values.
- All settings requests remain array entries in one `Promise.all`, so the six
  requests continue to start concurrently.

## Version & Compatibility Evidence

- No version or API changes.
- The existing `ui/package-lock.json` is lockfile v3 and resolves the tested
  core toolchain to Vite 8.2.2, Vitest 4.1.11, and TypeScript 7.0.2. Node
  24.16.0 satisfies the package engine range. No package manifest or lockfile
  was edited.
- The checkout lacked dependencies, so tests/build used a temporary link to an
  existing compatible WLA dependency tree; this produced no tracked changes.

## Open Questions

- Kimi cross-family review did not run (provider outage) and was waived by
  explicit human instruction — see "Blocker (waived)" below.

## Test Results

- Verification details are stored in `ai/tasks/wla-ui-settings-secrets-403-isolation/verification.md`.
- `cd ui && npx vitest run Settings.test.tsx`: 3/3 passed.
- `cd ui && npm run build`: passed (pre-existing chunk-size warning only, unrelated to this change).
- `uv sync --extra dev && uv run pytest tests/ -q`: full backend suite, 100% passed, 0 failed (this checkout's
  initial `pytest` run in verification.md failed only because dev extras were not yet installed in the fresh
  clone; not a regression from this change, which touches no backend files). The full suite ran clean in one
  pass — no order-sensitive flake was observed in this run.

## Diff Summary

- `/secrets` no longer aborts the Settings screen when demo mode returns 403.
  Provider/security/update/pack values remain visible, the Vault identifies
  demo-mode unavailability, and real settings permission errors retain their
  administrator guidance.

## Requested Review Focus

- Confirm concurrent request startup and the precise demo-mode-only 403
  classification; confirm no secret values or error details are exposed.
## Blocker (waived)

- 2026-09-01T01:34:42Z and 2026-09-01T01:38:10Z: Kimi cross-family review
  failed both attempts with `provider.api_error: 500` (same provider-outage
  class already logged against the sibling `wla-beta-p58` task). Per standing
  policy, no substitute provider was used and no additional retries were made.
- The human (josephp) explicitly instructed skipping the Kimi review step.
  Claude therefore performed the elevated final gate directly against the
  plan, diff, and verification evidence in lieu of a Kimi pass. Cross-family
  review remains an open item if Kimi's provider recovers before merge.

## Claude Final Gate (elevated, in lieu of blocked Kimi review)

- Diff reviewed in full (`git diff ui/src/screens/Settings.tsx` and the new
  `ui/src/screens/Settings.test.tsx`): matches the plan exactly — the
  `/secrets` promise is isolated in place with the same
  `.then(success, error)` typed-result idiom already used for
  `canViewLaunchPassport`; array order, count, and concurrency of the six
  `Promise.all` entries are unchanged.
- Confirmed `isDemoModeSecretsUnavailable` reads `demo_mode` from the
  freshly-fetched `securityRows` of the same `refresh()` cycle (not stale
  state), and requires both `ApiRequestError` and `status === 403`, so a
  non-403 `/secrets` failure (e.g. a 500) falls into the generic
  "temporarily unavailable" branch rather than being misclassified as
  demo-mode, and a real 403 on `/settings/providers` or `/settings/security`
  still propagates to the unmodified outer `catch` and shows the
  administrator-role message — the plan's highest-risk behavior.
  Confirmed by the two new tests, which pass.
- No secret values, vault contents, or raw error/response bodies are
  rendered in either new UI branch — only a fixed, bounded string per state.
- No dead code: the old `secretRows` identifier was fully replaced by
  `secretResult`; no unused variables or leftover branches.
- Independently reproduced all verification claims rather than trusting the
  implementer's report: `npx vitest run Settings.test.tsx` (3/3 pass),
  `npm run build` (passes, pre-existing chunk-size warning only), and a full
  `uv run pytest tests/ -q` backend run after installing dev extras (100%
  pass in one run, 0 failures) — confirms the change is frontend-only and
  introduces no backend regression.
- No new dependencies, no lockfile edits, no scope creep beyond the plan
  (the unrelated P5.8 demo-mode-honesty copy work on
  `ai/wla-beta-p58-settings-honesty` was not touched).
- Verdict: no blocking findings. Ready for the human to open a PR and merge
  at their discretion; cross-family Kimi review did not run due to a
  provider outage, waived by explicit human instruction rather than by
  Claude's own judgment.
