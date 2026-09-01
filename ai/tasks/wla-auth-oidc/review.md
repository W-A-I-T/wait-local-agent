# Review

## Changed Files

- Backend: `config.py`, `oidc.py`, `store.py`, `api/app.py`, and
  `api/auth_routes.py`.
- UI: `Login.tsx`, `PrincipalsAdmin.tsx`, and `api/types.ts`.
- Configuration/dependencies: `.env.example`, `pyproject.toml`.
- Tests: `tests/test_oidc_login.py` plus migration-version expectations in the
  existing migration suites.
- Docs/task metadata: Entra setup docs, configuration index, route manifest,
  and this task's implementation/status artifacts.

## Risk Areas

- Security review verdict: conditionally ready for cross-family verification;
  no known critical or high-severity issue was found in the static review, but
  OIDC must remain disabled until the pending runtime and lockfile gates pass.
- Authlib/Entra discovery and token validation are external integration points;
  the callback deliberately accepts only Authlib's validated `userinfo` map.
- The callback explicitly checks the configured tenant ID and issuer, and the
  auto-provision path checks the exact `tid`, configured WAIT client, and fixed
  `viewer` role. Unknown identities fail closed.
- `next` is validated at login and again before callback redirect; no Host
  header is used to construct the redirect URI.
- Client secrets and session signing material are vault-backed and excluded
  from responses/audit details. Access and ID tokens are not persisted or
  logged.
- Migration 9 is additive and foreign-key cascades identity links when a
  principal is removed. Concurrent auto-provisioning is handled by the
  deterministic identity link and SQLite integrity check.
- The dependency lockfile could not be refreshed in this sandbox; this is the
  principal release-readiness risk.

## Version & Compatibility Evidence

- Added `authlib>=1.8,<2.0` and `itsdangerous>=2.2,<3.0`. Live PyPI checks
  identified Authlib 1.8.0 as the current 1.x release and itsdangerous 2.2.0
  as the current stable release at implementation time. Authlib's Starlette
  integration supports discovery, authorization-code exchange, and PKCE; the
  implementation uses the documented `server_metadata_url` and `S256`
  configuration. See [Authlib on PyPI](https://pypi.org/project/Authlib/),
  [itsdangerous on PyPI](https://pypi.org/project/itsdangerous/), and
  [Authlib Starlette OAuth documentation](https://docs.authlib.org/en/stable/oauth2/client/web/starlette.html).
- Microsoft reply-URL behavior was checked against [Microsoft's reply URL
  guidance](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url);
  deployment docs retain the configured-base-URL and trusted-host constraints.
- `uv.lock` remains stale relative to `pyproject.toml` until a network-enabled
  lock refresh is performed.

## Open Questions

- Claude must run the full test/coverage/security/browser gate.
- Human deployment review must confirm the Entra app registration is
  single-tenant and its reply URL exactly matches the configured base URL.

## Test Results

- Passed: Python compilation, Ruff on changed Python files, TypeScript build
  checking, JSON validation, and `git diff --check`.
- Blocked: full mypy by missing `slowapi` in this environment; Bandit is not
  installed; UI build and Vitest are blocked by write permission on existing
  `ui/node_modules/.vite-temp`.
- Not run by contract: pytest and Playwright. Full coverage/Bandit remain
  Claude-owned gates.

## Diff Summary

- OIDC is additive to local login: disabled-by-default status/login routes,
  tenant-pinned Authlib client, stable short-lived handshake cookie, DB-backed
  session creation, principal identity linking, optional bounded viewer
  provisioning, admin configuration, and UI/documentation support.

## Requested Review Focus

- Verify the open-redirect matrix, state-mismatch handling, explicit `tid` and
  issuer checks, no-token persistence/logging, vault-only secret handling,
  migration compatibility, route manifest completeness, and the exact
  server-side session creation path.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after two scoped Codex fixes (Login test Router wrapper;
coverage top-up for callback/config branches). Cleanest slice yet — the
gate-lesson constraints appended to plan.md eliminated the manifest/mypy/e2e
failure classes seen in PR 1-2b.

Security review of oidc.py + auth_routes.py OIDC surfaces: oid-authoritative
identity resolution with email-invite upgrade and concurrent-login safety;
auto-provision hard-gated (enabled flag AND tid claim match AND viewer-only
AND existing client); explicit callback assertion tid == configured tenant
(403) as defense-in-depth over Authlib's iss/aud/nonce/state validation;
validate_next_path decode-loop rejects //host, schemes, backslashes;
authorize_redirect failures map to a non-leaking 502; client secret is
write-only to the vault and never echoed.

Live smoke on a branch build (port 18792): disabled status/404 login; PUT
config incomplete-enable 422; unauthenticated PUT 401; enable flips status;
open-redirect next rejected 400; upstream tenant-not-found (real Microsoft
AADSTS90002 for a fake GUID) maps to graceful 502; secret absent from GET;
Login screen conditionally renders "Sign in with Microsoft" with zero console
errors. Full interactive Entra login requires a real tenant — happy path is
covered by the stubbed-client unit tests (28 passing).

Test evidence: full suite 95.01% vs 95% gate; mypy clean on 290 files; ruff
clean; UI 367/367 including new Login/PrincipalsAdmin OIDC tests.
