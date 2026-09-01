# Implementation Notes

## Summary

- Implemented tenant-pinned Microsoft Entra OIDC authorization-code + PKCE on
  the existing server-side principal/session model.
- Added migration 9 for `principal_identities`, including email-invite
  consumption and permanent Entra object-ID links.
- Added fail-closed identity resolution, explicit `tid` validation, bounded
  viewer-only auto-provisioning, local-path `next` validation, rate-limited
  login/status routes, and stable Starlette handshake-cookie signing via the
  Fernet vault.
- Added admin configuration and identity-link CRUD, Login and People & Access
  UI, Entra setup documentation, route-surface classifications, and focused
  stub-client tests.

## Commands Run

- `pwd`, `git remote -v`, `git status --short --branch` — verified the target
  checkout is `W-A-I-T/wait-local-agent` on
  `ai/wla-auth-oidc-auth-oidc`.
- `python3 -m py_compile ...` — passed for changed Python modules/tests.
- `ruff check` on changed Python modules/tests — passed.
- `npx tsc -b --pretty false` from `ui/` — passed.
- `python3 -m json.tool docs/ai-workflow/surface-coverage.json` — passed.
- `git diff --check` — passed.
- `npm run build` and focused Vitest — blocked by `EACCES` writing the
  existing `ui/node_modules/.vite-temp` directory.
- `mypy` — full invocation is blocked because the Codex environment lacks the
  repository's `slowapi` import; `--ignore-missing-imports` reached only two
  pre-existing unused-ignore errors outside this task.
- `bandit` is not installed in the Codex environment; Claude owns the
  security scan. `pytest`/Playwright were not run per the task contract;
  Claude owns those checks.
- `uv lock`/`uv lock --check` were attempted with a temporary cache but were
  blocked by unavailable DNS access to `pypi.org`; `uv.lock` was not edited.

## Files Touched

- `.env.example`; `pyproject.toml`; `src/wait_local_agent/{config.py,oidc.py,store.py}`;
  `src/wait_local_agent/api/{app.py,auth_routes.py}`; and
  `tests/test_oidc_login.py`.
- UI: `ui/src/api/types.ts`, `ui/src/screens/Login.tsx`, and
  `ui/src/screens/PrincipalsAdmin.tsx`.
- Docs: `docs/README.md`, `docs/ai-workflow/surface-coverage.json`,
  `docs/getting-started/{configuration.md,entra-oidc.md}`.
- Migration-version expectation updates in the existing migration suites.
- Task records: `ai/tasks/wla-auth-oidc/{implementation.md,review.md,status.json}`.

## Follow-Up

- Refresh and commit `uv.lock` in a network-enabled dependency environment;
  its contents remain unchanged because this sandbox could not resolve PyPI.
- Run the full Claude-owned pytest/coverage, Bandit, Vitest, Playwright, and
  production-readiness checks. The plan's 95% coverage floor remains a gate.
- Confirm the Entra application's exact reply URL and `WAIT_TRUSTED_HOSTS`
  value in the deployment environment before enabling OIDC.

## Coverage Follow-Up

- Extended `tests/test_oidc_login.py` with stubbed-client coverage for disabled,
  invalid-redirect, provider-error, callback-validation, session, configuration,
  and identity-link branches, including vault/error and auto-provision guards.
- Extended `tests/test_config.py` with environment-helper permutations for
  optional numeric values and an unavailable Fernet vault fallback.
- `ruff check tests/test_oidc_login.py tests/test_config.py`, Python compilation,
  and `git diff --check` pass after the coverage additions. Targeted mypy found
  no errors in either test file; the repository invocation remains blocked by
  the unavailable `slowapi` dependency and two pre-existing unused-ignore errors.
- Pytest was intentionally not run per the task contract; static validation is
  recorded after these additions when available.
