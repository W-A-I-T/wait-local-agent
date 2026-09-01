# Review

## Changed Files

- Store: additive principal detail, safe credential summary, activation,
  display-name, revocation, and role-removal methods.
- API: new `src/wait_local_agent/api/auth_routes.py`, included from
  `api/app.py`.
- CLI: new authenticated `principals` command group.
- UI: new MSP-admin-gated `/settings/access` screen, route/sidebar/context/type
  wiring, and focused tests.
- Tests: focused principal API coverage and UI behavior coverage.

## Security Review

- All API operations require `AdminAccess` and `_require_msp_operator`.
- Every write operation refuses demo mode before touching the store.
- Tokens are generated server-side and never logged, audited, or returned by
  list/detail reads; only a one-time issuance response contains the raw token.
- Credential list responses contain only a 12-character hash prefix, active
  state, and creation time.
- Self-deactivation and self-removal of `msp_admin` compare against the
  authenticated context principal ID, not request input.
- Principal deactivation is an `active` flag update, preserving audit history.
- Client-role assignment verifies that the target client exists and excludes
  the reserved quarantine client.

## Version & Compatibility Evidence

No dependency, schema, or resolver changes. Validation used the repository’s
locked compatible versions; see `implementation.md` for the exact versions.

## Test Results

- Ruff, mypy, Bandit, TypeScript build, Vite build, and all 363 UI tests passed.
- CLI bootstrap smoke check and existing principal unit tests passed.
- Focused Python HTTP tests remain pending because the local FastAPI
  TestClient/ASGI runtime hangs even for a minimal baseline app; this is an
  environment/tooling limitation, not an observed application assertion.

## Remaining Risk

The required CI/runtime request-level Python test pass is still outstanding and
must be completed before merge. Human approval and the required cross-family
read-only review remain required.

## Requested Review Focus

Verify one-time token exposure, double privilege gating, self-lockout guards,
demo-mode refusal on every mutation, safe hash-prefix handling, and preservation
of audit history.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after two scoped Codex test fixes (httpx DELETE json kwarg;
audit newest-first ordering) and one E501 wrap.

Security review of api/auth_routes.py: all mutations double-gated
(AdminAccess + msp_operator) with demo-mode write refusal; one-time raw token
only in the issuance response; self-deactivation and self-msp_admin-removal
guards; quarantine client excluded from role grants; extra="forbid" models;
audit event per mutation. Note: credential revocation matches by 12-char hash
prefix after an ownership pre-check scoped to the target principal — verified
live that revoke-by-prefix works and cannot cross principals.

Validation run by Claude (Codex sandbox cannot run TestClient):
- tests/test_principal_admin_api.py + test_principals.py + test_rbac.py: 24/24.
- ruff (src+tests) clean after E501 fix; mypy clean on auth_routes.py/store.py.
- Vitest PrincipalsAdmin: 3/3 (Codex ran the full 363-test UI suite green).
- Live end-to-end on a branch build (uvicorn + compiled ui/dist, port 18790):
  browser renders the msp_admin-gated People & Access screen (non-admin path
  shows "MSP administrator access required"; admin path shows create form and
  listing). Full lifecycle via live API: create tech-jane -> issue credential
  -> new bearer resolves fail-closed with no roles -> revoke by prefix ->
  post-revoke 401 -> audit shows created/issued/revoked newest-first.
- Browser-pane synthetic clicks were unreliable this session (pane not
  compositing); form interactions verified via component tests + live API.
