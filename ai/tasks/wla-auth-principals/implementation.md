# Implementation Notes

## Summary

Implemented the principals/RBAC management slice on
`ai/wla-auth-principals-auth-principals`.

- Added additive store accessors for principal activation/display updates,
  credential revocation and safe summaries, role removal, and joined principal
  details.
- Added the double-gated `/auth/principals` API with demo-mode write refusal,
  server-generated one-time bearer tokens, self-lockout guards, and audit
  events for mutations.
- Added authenticated `principals` CLI commands for bootstrap and ongoing
  management.
- Added the MSP-admin-only People & Access screen at `/settings/access`, with
  role/credential controls, one-time token reveal/copy, and the Microsoft Admin
  capability-grant link.
- Added focused API and UI tests.

## Security Notes

Raw bearer tokens are generated with `secrets.token_urlsafe(32)`, returned only
from the issuance operation, and are not included in audit details or principal
list responses. Principal and credential deactivation continue to use the
existing `active = 1` resolver semantics; principal deactivation does not
delete history.

## Version & Compatibility Evidence

No dependencies or migrations were added. The repository lock/configuration
already pins the compatible stack used for validation: FastAPI 0.139.0,
Starlette 1.3.1, httpx 0.28.1, Vite 8.2.2, and Vitest 4.1.10. No version or
API upgrade was necessary for this additive change.

## Validation

- Ruff: passed for changed Python source/tests.
- mypy: passed for changed Python source.
- Bandit: passed for the new auth router.
- Existing principal unit tests that avoid HTTP dispatch: passed.
- CLI bootstrap smoke check (create, issue, list): passed; only the safe hash
  prefix is shown by list.
- UI TypeScript build and Vite build: passed.
- UI suite: 70 files, 363 tests passed, including the new screen tests.
- Python request-level API tests were not runnable to completion in this
  environment: even a minimal FastAPI app request hangs under the installed
  Starlette/TestClient runtime, before application route logic executes.

## Files Touched

`src/wait_local_agent/store.py`, `src/wait_local_agent/api/auth_routes.py`,
`src/wait_local_agent/api/app.py`, `src/wait_local_agent/cli.py`,
`tests/test_principal_admin_api.py`, `ui/src/screens/PrincipalsAdmin.tsx`,
`ui/src/screens/PrincipalsAdmin.test.tsx`, `ui/src/routes.tsx`,
`ui/src/app/Sidebar.tsx`, `ui/src/app/DashboardContext.tsx`,
`ui/src/api/types.ts`, `ai/tasks/wla-auth-principals/implementation.md`,
`ai/tasks/wla-auth-principals/review.md`, and
`ai/tasks/wla-auth-principals/status.json`.

## Follow-Up

Run the focused Python API tests in the project CI/runtime with a functioning
HTTP test client, then complete the required read-only cross-family review and
human merge gate.

Resolved the gitleaks false positives for the principals UI fixture and diagnostics placeholders.

## CI Coverage Follow-Up

- Classified all `/auth/principals` HTTP routes and `principals` CLI commands in
  the runtime surface manifest as admin-gated surfaces.
- Added API error/guard coverage and `CliRunner` coverage for the principal
  management paths. Local pytest remains intentionally unrun because the
  installed Starlette/TestClient runtime hangs before route dispatch; Claude
  should perform the authoritative CI verification.
