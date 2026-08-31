# Review

## Changed Files

- `src/wait_local_agent/rbac.py`
- `src/packs/microsoft_admin/insights.py`
- `tests/test_microsoft_admin_capability_access.py`
- `tests/test_microsoft_admin_graph_client.py`
- `tests/test_microsoft_admin_insights.py`

## Risk Areas

- The shared capability gate now changes denied-response details while keeping status 403 and all successful authorization behavior unchanged.
- Scope mismatch classification must not expose tenant data; responses use fixed remediation text and do not echo client IDs or tokens.
- Remediation consumers now receive only smart-action IDs present in `default_registry`; user disable remains available through its existing REST draft endpoint, but is not advertised as a smart action.

## Version & Compatibility Evidence

- No dependency or external API version changes. `uv lock --check --offline` passed against the existing 239-package lock; relevant locked versions remain FastAPI 0.139.0, httpx 0.28.1, pytest 9.1.1, ruff 0.15.20, mypy 1.20.2, slowapi 0.1.10, and urllib3 2.7.0. The intentional internal API change is the documented 403 error body.
- No migration, SDK, or stale-version concern was introduced.

## Open Questions

- None for the implementation. CI should complete the full backend suite in a synchronized environment.

## Test Results

- Passed: `ruff check src tests`.
- Passed: targeted mypy, compileall, lock check, 9 Microsoft Admin graph/insights tests, and registry-resolution smoke test.
- Not fully verified locally: the bounded full suite timed out after 43 passing tests at an unrelated app-backed test; the new app-backed capability test also hangs under available local environments.

## Diff Summary

- Capability denials are now actionable and preserve fail-closed authorization.
- Microsoft Admin recommendations and findings no longer deep-link to nonexistent smart actions.
- Regression coverage includes all three denial reasons and catalog-to-registry resolution.

## Requested Review Focus

- narrow diff review
- Confirm error classification for persisted principals with grants across multiple client scopes.
- Confirm the REST-only user-disable draft is intentionally excluded from the smart-action catalog.
