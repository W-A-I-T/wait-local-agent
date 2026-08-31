# Review

## Changed Files

- `ui/src/screens/Approvals.tsx`
- `ui/src/screens/__tests__/Approvals.test.tsx`
- Task evidence: `ai/tasks/wla-beta-p17/implementation.md`, `review.md`, and `status.json`

## Risk Areas

- The Execute control is now rendered independently of the approve/reject/save controls so viewers can see why a mapped action is unavailable; the `canWrite` gate remains enforced in the disabled expression.
- Safe Mode messaging is limited to approved, not-yet-completed HaloPSA requests whose existing `can_execute` state is false and whose existing global HaloPSA write posture is not ready.
- Unmapped action types still cannot invoke `executeApproval`; they render the workflow note and no Execute button.

## Version & Compatibility Evidence

- No version or API changes.
- Dependencies were installed from the committed `ui/package-lock.json` with `npm ci`; the existing package manifest requires Node `^22.22.2 || ^24.15.0 || >=26.0.0`, and validation used Node `v24.16.0`/npm `11.13.0`.
- The build used the lockfile-resolved Vite `8.2.2`; no newer dependency or API was selected because this UI-only change does not alter dependency or integration contracts.
- `npm ci` reported 0 vulnerabilities. Remaining compatibility concern is the pre-existing Vite config-loader warning, not a changed API.

## Open Questions

- None for the scoped implementation. Human/reviewer should confirm the exact inline copy and the intended separate workflow destination for each unmapped provider action.

## Test Results

- Targeted approval and endpoint tests: 2 files, 19 tests passed.
- Full suite: 57 files, 287 tests passed on both required runs; an additional dot-reporter run confirmed the same result.
- Production build: passed (`tsc -b` and Vite build).
- Warnings: existing Vite config-loader warning; existing unrelated React `act(...)` warnings in `ConnectorInstances` and `ApplianceHealth` tests.

## Diff Summary

- Added clear workflow-only messaging for unmapped approvals, role-specific Execute hints for viewers, and a Safe Mode hint for gated HaloPSA execution without changing endpoint mappings or execution behavior.

## Requested Review Focus

- narrow diff review

## Prior Run Note

- Prior implementation attempt exited with status 143 at 2026-08-31T01:29:37Z; the task was rerun and completed with the validation above.
