# Implementation Notes

## Summary

- Added one typed connector-setup map for the 14 connector cards. The map uses
  only names verified in `src/wait_local_agent/config.py` and exposes the six
  supported RMM vendor families under the combined RMM card.
- Added expandable, provider-specific setup guidance to Connectors, including
  exact environment names, the fernet-backend caveat, safety gates, and the
  per-client instance link for HaloPSA and ConnectWise.
- Clarified that Connector Instance form values are encrypted credentials,
  preserved the existing request flow, and named the generated reference on
  the partial-failure path.
- Retitled and documented Settings' advanced vault form and added a datalist
  of known connector environment names while keeping arbitrary secret names
  supported.

## Commands Run

- `pwd`, `git remote -v`, `git status --short --branch`: verified
  `/home/josephp/wla-beta-p24`, remote `W-A-I-T/wait-local-agent`, and branch
  `ai/wla-beta-p24-connector-truth`. The pre-existing untracked worker lock was
  left untouched.
- `rg` verification against `src/wait_local_agent/config.py`: all 84 unique
  `WAIT_*` names used by `connectorSetup.ts` were found; no missing names.
- `cd ui && npm ci`: completed successfully; 141 packages added and 0 audit
  vulnerabilities. The lockfile was not changed.
- Targeted UI tests: 4 files and 37 tests passed.
- `cd ui && npm test -- --run`: two consecutive full runs passed, each with 60
  test files and 298 tests.
- `cd ui && npm run build`: passed; 1,873 modules transformed and production
  assets generated.
- Validation emitted the existing Vite `configLoader: 'native'` import-extension
  warning and existing large-chunk warning. Neither is caused by this change.

## Files Touched

- `ui/src/lib/connectorSetup.ts`
- `ui/src/screens/Connectors.tsx`
- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/screens/Settings.tsx`
- `ui/src/styles.css`
- `ui/tests/connectorSetup.test.ts`
- `ui/tests/Connectors.test.tsx`
- `ui/tests/wla-wp17.test.tsx`
- `ui/src/screens/__tests__/ConnectorInstances.test.tsx`
- `ai/tasks/wla-beta-p24/implementation.md`
- `ai/tasks/wla-beta-p24/review.md`
- `ai/tasks/wla-beta-p24/status.json`

## Follow-Up

- No follow-up work is required for the scoped task. The pre-existing Vite
  warnings remain for a separate maintenance change.
