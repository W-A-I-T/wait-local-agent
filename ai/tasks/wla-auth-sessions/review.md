# Review

## Changed Files

- Server auth/session code: `sessions.py`, `store.py`, `rbac.py`,
  `api/auth_routes.py`, `api/app.py`, `config.py`, `.env.example`.
- Python regression/acceptance tests and migration expectations under `tests/`.
- Dashboard login/session state, headers, account UI, styles, and tests under
  `ui/`.

## Risk Areas

- Auth precedence and scope parity: an explicit Authorization header always
  selects bearer auth; cookies are used only when the header is absent.
- Session security: only SHA-256 token digests are persisted, tokens are
  generated server-side, logout marks rows revoked, and inactive principals
  cannot resolve sessions.
- CSRF: unsafe cookie-authenticated requests require `X-WAIT-CSRF`; bearer
  requests remain exempt. Cookie defaults are HttpOnly, SameSite=Lax, Path=/,
  and Secure unless explicitly disabled for local HTTP development.
- Migration 8 must preserve existing SQLite data and migration expectations.
- The API TestClient hang prevented end-to-end HTTP assertions in this
  environment; CI must rerun them.

## Version & Compatibility Evidence

- No dependency or runtime version changes. The implementation uses the
  existing standard-library `secrets`/`hashlib` primitives and FastAPI/Starlette
  response cookie APIs; no SessionMiddleware or new package was introduced.
- Local compatibility evidence: FastAPI 0.139.0, Starlette 1.3.1, httpx
  0.28.1, slowapi 0.1.10, Node 24.16.0, npm 11.13.0, Vite 8.2.2, Vitest
  4.1.11, React 19.2.8. UI dependency lockfile was unchanged.
- The Starlette/httpx TestClient combination emits its existing deprecation
  warning and hangs on baseline requests in this environment; this is the
  remaining compatibility risk to verify in CI. No upgrade was made because
  the task explicitly requires no new Python dependencies and the existing
  application stack is the repository's declared compatibility target.

## Open Questions

- CI should confirm the API and Playwright tests against its supported Python
  dependency set and browser service.
- Human/Claude reviewer should confirm whether future OIDC sessions should use
  the same `auth_method` values and TTL configuration, as anticipated by the
  migration contract.

## Test Results

- Passed: compileall, ruff, mypy, focused bandit scan, session/config tests,
  focused RBAC tests, full UI Vitest (367 tests), focused UI Vitest (27 tests),
  UI build, Playwright test listing, and `git diff --check`.
- Blocked: Python API acceptance tests timed out after 30 seconds because the
  installed Starlette/httpx TestClient harness also hangs on the unchanged
  `/healthz` path. This is explicitly not reported as a pass.

## Diff Summary

- Local DB-principal credentials now exchange for opaque HttpOnly sessions;
  bootstrap credentials remain bearer-only. Session auth reuses principal role,
  client scope, and capability resolution, touches idle expiry within an
  absolute limit, and revokes on logout/deactivation. The UI probes sessions
  before falling back to bearer auth and gives users a Sign out action.

## Requested Review Focus

- Verify bearer-over-cookie precedence and CSRF propagation through every RBAC
  dependency.
- Verify raw-token non-disclosure, server-generated session IDs, revocation
  replay failure, expiry semantics, and Secure-cookie deployment defaults.
- Verify migration 8 on an existing database and rerun the blocked API and
  Playwright acceptance tests in CI.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after five scoped Codex fixes (spine_p0 indentation; session-route
surface-manifest entries; logout cookie-jar assertion; capability-grant test
semantics — global grants legitimately cover all clients; missing create_client
in test setup).

rbac.py diff review: bearer branch untouched and always wins when an
Authorization header is present; session branch validates hash, revocation,
idle+absolute expiry, enforces X-WAIT-CSRF on POST/PUT/PATCH/DELETE, touches
last-seen, and reuses _principal_auth_context so role/scope/capability
semantics are identical to bearer principals. approver_id falls back to
principal_id for audit attribution.

Live validation on a branch build (uvicorn + compiled ui/dist, port 18791):
- CLI bootstrap: principals create -> issue-credential (one-time) -> add-role.
- POST /auth/login/local sets HttpOnly SameSite=Lax Path=/ cookie bound to the
  principal; bootstrap env tokens get session_created=false (break-glass kept).
- Security matrix all passing live: cookie GET works with correct scope;
  cookie POST without CSRF header -> 403 csrf_required; with header -> 200;
  wrong bearer + valid admin cookie -> 401 (bearer precedence, cookie never
  rescues); logout 200; cookie replay after logout -> unauthenticated.
- Login screen renders as the unauthenticated landing view; zero console errors.

Test evidence: full suite 95.02% vs 95% gate; new suites test_sessions,
test_auth_sessions_api, rbac additions all green; regression contract suites
(test_api, client_scope_enforcement, end_user_support, capabilities, spine_p0,
store) pass unmodified. ruff/mypy clean.
