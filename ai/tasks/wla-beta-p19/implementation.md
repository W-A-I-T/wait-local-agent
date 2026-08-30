# Implementation Notes

## Summary

- Added a structured `capability_required` 403 contract to the shared Microsoft Admin capability gates.
- Bootstrap environment tokens now report `no_principal`; persisted principals without a grant report `no_grant`; a grant for another tenant reports `client_scope_mismatch`.
- Preserved the existing role, demo-mode, principal-grant, and client-scope authorization boundaries; no capability is auto-granted.
- Corrected Microsoft Admin remediation IDs to the registered smart actions and removed the user-disable catalog item because it only has a REST draft endpoint.

## Commands Run

- `ruff check src tests` — passed.
- `mypy src/wait_local_agent/rbac.py src/packs/microsoft_admin/insights.py` — passed.
- `PYTHONPATH=src /usr/bin/python3 -m compileall -q src tests` — passed.
- `UV_CACHE_DIR=/tmp/wla-beta-p19-uv-cache uv lock --check --offline` — passed; 239 packages resolved.
- `PYTHONPATH=src /usr/bin/python3 -m pytest -q tests/test_microsoft_admin_graph_client.py tests/test_microsoft_admin_insights.py` — passed, 9 tests.
- Direct capability-gate smoke test — passed for bootstrap `no_principal` and wrong-client `client_scope_mismatch` responses.
- `timeout 120s env PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest` — timed out with exit 124 after 43 passing tests; no assertion failure was emitted. The same environment hangs in app-backed capability tests during app setup.
- `UV_CACHE_DIR=/tmp/wla-beta-p19-uv-cache uv run pytest ...` — blocked before test execution because the sandbox cannot fetch locked `urllib3==2.7.0` without network access.

## Files Touched

- `src/wait_local_agent/rbac.py`
- `src/packs/microsoft_admin/insights.py`
- `tests/test_microsoft_admin_capability_access.py`
- `tests/test_microsoft_admin_graph_client.py`
- `tests/test_microsoft_admin_insights.py`
- `ai/tasks/wla-beta-p19/implementation.md`
- `ai/tasks/wla-beta-p19/review.md`
- `ai/tasks/wla-beta-p19/status.json`

## Follow-Up

- Re-run the complete backend suite in CI or a fully synchronized locked environment; local bounded execution was limited by the sandbox dependency/app setup behavior.
