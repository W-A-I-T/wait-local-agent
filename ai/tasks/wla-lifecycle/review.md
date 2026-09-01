# Review

## Changed Files

- Backend lifecycle: `src/wait_local_agent/{api/app.py,backup.py,models.py,scheduler.py,store.py}`.
- Tests: `tests/test_backup_lifecycle.py` plus four migration pin updates.
- UI: backup types, Overview status, Scheduled Jobs creation, Schedules filtering,
  and the corresponding Vitest coverage.
- Operations and governance: `docs/operations/{backups-and-vault.md,updates.md}`
  and `docs/ai-workflow/surface-coverage.json`.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- Migration 13 must remain append-only and compatible with existing startup
  migration ordering.
- Scheduled backups use the existing Fernet/vault-reference path and write only
  appliance-local artifacts; API responses expose metadata, never contents or
  key material.
- Admin/MSP-operator gating, demo-mode refusal, audit records, sanitized failure
  summaries, and backup retention are the main security/control paths.
- Retention pruning is deliberately non-fatal after a successful backup, with its
  failure recorded for operator visibility.

## Version & Compatibility Evidence

No version or API changes. Existing UI compatibility was verified with Node
v24.16.0, Vite v8.2.2, Vitest v4.1.11, TypeScript v7.0.2, and React v19.2.8;
the package manifest/lock were not changed. No new dependency was introduced.
The new routes and migration were validated against the repository's current
FastAPI/store interfaces. Remaining environment risk is the missing local
`slowapi`/`itsdangerous` runtime tooling and unavailable Bandit, not a changed
dependency constraint.

## Open Questions

- Confirm the operator's deployment-specific backup destination permissions and
  host scheduler wiring before production rollout.
- Complete the required read-only Kimi review and Claude final gate.

## Test Results

- Passed: changed-file Ruff, targeted mypy, compileall, diff check, public-surface
  audit, full UI Vitest (83 files/471 tests), UI TypeScript/Vite build, and a
  populated-environment backup/migration smoke test.
- Blocked: full mypy because six `slowapi` imports are absent from the local
  environment; Bandit executable unavailable.
- Not run by contract: pytest and Playwright.

## Diff Summary

- The appliance can schedule or manually request encrypted local backups, persist
  and page outcomes, show the latest status to authorized operators, retain a
  bounded artifact set, and reference restore-exercise evidence. Update docs now
  describe signed verification, immutable image handling, startup migrations,
  health checks, and restore-based rollback.

## Requested Review Focus

- Verify migration 13/schema pin coverage and scheduler execution wiring.
- Verify route RBAC/demo behavior, audit semantics, failure sanitization, and the
  no-content/no-key API boundary.
- Verify the Overview and Scheduled Jobs changes preserve existing flows and that
  `Settings.tsx` remains untouched.
