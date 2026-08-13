# Review

Use this exact structure for `ai/tasks/<task_id>/review.md`.

## Changed Files

- `src/wait_local_agent/config.py`
- `src/wait_local_agent/rbac.py`
- `src/wait_local_agent/api/app.py`
- `tests/test_api.py`
- `tests/test_rbac.py`
- `ai/tasks/wla-wp20-approval-tenancy/implementation.md`
- `ai/tasks/wla-wp20-approval-tenancy/review.md`
- `ai/tasks/wla-wp20-approval-tenancy/status.json`

## Risk Areas

- Approval object access is scoped from the install-level authenticated
  principal, not from caller input.
- Workflow-run detail keeps the run visible but omits an embedded approval when
  that approval is outside the authenticated install scope.
- The scope check must precede payload/status mutation and both HaloPSA
  execution paths.
- 404 responses must not disclose whether a foreign approval ID exists.
- Legacy rows with no `client_id`, demo/admin contexts, and no-tenant installs
  intentionally retain compatibility behavior.
- For an unbound non-admin, a supplied list `client_id` is preserved only as a
  narrowing filter; a bound non-admin remains locked to its bound tenant.

## Version & Compatibility Evidence

No version or API changes. `pyproject.toml` and `uv.lock` were not modified;
there are no new dependencies or schema migrations. The follow-up changes are
limited to the workflow-run response guard and API regression coverage.

## Questions

- None outstanding. Review and verification were completed before this branch
  was opened for merge.

## Test Results

- Passed: `.venv/bin/ruff check src tests`.
- Passed: targeted mypy for the changed API/RBAC/config implementation and
  regression tests.
- Passed: `git diff --check` and the required empty config/RBAC diff.
- Passed: `timeout 500 .venv/bin/python -m pytest tests/test_api.py
  tests/test_rbac.py -p no:warnings -q` — 48 passed, exit 0.
- Full suite `pytest tests/` passes except the two pre-existing
  environment-dependent tests
  `tests/test_knowledge.py::test_docling_parser_missing_dependency_errors_cleanly`
  and `tests/test_knowledge.py::test_qdrant_local_backend_missing_dependency_errors`,
  which fail identically on a clean `origin/main` checkout in the same
  environment (docling/qdrant are installed while those tests expect them
  absent). Unrelated to this change; untouched by this task.
- Verified regression history: the original implementation broke the
  pre-existing test `test_auth_role_approver_identity_and_client_filters`
  (unbound viewer narrowing with `?client_id=`); the follow-up fix restores
  narrowing for unbound non-admins and the test now passes.

## Diff Summary

- Added `WAIT_CLIENT_ID` to settings/auth context, made approval list filters
  tenant-aware, rejected foreign approval detail/edit/update/execute requests
  with 404 before any state or connector side effect, and hid foreign embedded
  approvals from workflow-run detail without changing the run shape.

## Review Focus

- Elevated authorization change: independent cross-family review plus a final
  gate were both completed before merge was proposed.

## Ownership Check

- Implementation stayed within assigned ownership: config, RBAC, API, tests,
  and task artifacts only.
- Added focused API coverage for foreign embedded approval redaction, successful
  in-scope payload editing, and no-filter bound-tenant list scoping.
- Blocked paths, including `store.py`, `halopsa.py`, CI, and desktop packaging,
  were not touched.
- No parallel writer was used; this task was marked non-parallel-safe because
  it shares `api/app.py`, `rbac.py`, and `config.py` with concurrent work.
- Independent cross-family review and the required elevated final gate were
  both completed.
- Human merge and deployment authority remains in place.
