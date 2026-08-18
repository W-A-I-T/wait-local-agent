# Review

## Changed Files

- `tests/test_client_scope_enforcement.py`
- `ai/tasks/wla-ticket-scope-regression/implementation.md`
- `ai/tasks/wla-ticket-scope-regression/review.md`
- `ai/tasks/wla-ticket-scope-regression/status.json`

## Risk Areas

- The regression guard must remain non-vacuous: beta detail rows are seeded
  and proven present before the alpha-scoped API calls.
- The test asserts exact status/body behavior and includes alpha positive
  controls, so a globally empty or always-404 implementation cannot pass.
- No production code, migrations, secrets, auth configuration, or data
  boundary behavior was changed.

## Version & Compatibility Evidence

- No version or API changes.
- The existing lock/configuration and environment use FastAPI 0.139.0,
  Starlette 1.3.1, httpx 0.28.1, pytest 9.1.1, and Python 3.12.3; no new
  dependency or SDK was introduced. `pip check` passed.
- `uv lock --check` could not resolve in this network-restricted sandbox, so
  compatibility was not refreshed against the package index. The test uses
  only the already-present pytest/FastAPI TestClient API.

## Open Questions

- The targeted API test needs to be rerun in a working TestClient environment;
  the current environment hangs on the first request even in a minimal
  FastAPI reproduction.

## Test Results

- Passed: Ruff check, Python compilation, `git diff --check`, and `pip check`.
- Blocked by environment: targeted pytest execution and therefore the full
  `tests/test_client_scope_enforcement.py` command were not allowed to finish
  because Starlette/FastAPI TestClient hangs in the current environment.

## Diff Summary

- Added one focused backend regression test covering cross-client ticket list
  isolation and ticket-detail summary/context/notes/status-history behavior.

## Requested Review Focus

- Confirm the test is test-only, non-vacuous, deterministic, and matches the
  exact per-endpoint contract in `plan.md`.
- Confirm no beta note, status-history data, or ticket identifier is exposed
  to the alpha-bound technician principal.

## Blocker

- 2026-08-18T03:46:59Z: Kimi cross-family review exited with status 1.
- The canonical attempt failed on Kimi storage writes in the read-only home;
  a writable `/tmp` retry could not find credentials without relocating the
  existing credential store.

## Claude Final Gate (elevated)

- Verdict: PASS. Test-only change; no `src/` or `ui/` files touched
  (`git diff --name-only origin/main` = `tests/test_client_scope_enforcement.py`).
- Authoritative run in project venv: `tests/test_client_scope_enforcement.py`
  9 passed (was 8 before this task). Executed with
  `/home/josephp/wait-local-agent/.venv/bin/python -m pytest ... -p no:cacheprovider`.
- Contract verified against `src/wait_local_agent/api/app.py`: list excludes
  other clients + `?client_id=beta` → 403; `/summary` and `/context` → 404 via
  scoped `get_ticket`; `/notes` and `/status-history` → `200 []` (bound scope
  resolves to alpha; scoped store read empty).
- Non-vacuous: beta note + status-history seeded and asserted present via
  beta-scoped store reads; own-client positive controls confirm alpha sees its
  own notes/history, so the empty/404 beta results demonstrate scoping.
- Mutation proof (throwaway, not committed): forcing the scope resolver to the
  wrong tenant made `/notes` leak `beta-confidential-note` and `/summary` stop
  404-ing — confirming the committed assertions catch a real scope regression.
- Kimi cross-family review: environmentally BLOCKED (Kimi sandbox cannot run
  Starlette/FastAPI TestClient; credential-store write failed in read-only
  $HOME). Its static checks (ruff / py-compile / `git diff --check` / `pip check`)
  passed. Per workflow policy the failed handoff is recorded and ownership of
  that gate returns to the human; no reviewer substitution was made.
- Merge authority remains with the human.
