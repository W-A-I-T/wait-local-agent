# Implementation Notes

## Summary

- Added the optional `WAIT_CLIENT_ID` install scope to settings and resolved it
  onto every authenticated `AuthContext`, matching the PR #51 tenancy hunk.
- Added approval-specific scope resolution: admins may use the requested list
  filter; bound non-admins always use the authenticated install tenant, while
  unbound non-admins retain a caller-supplied list filter as a narrowing-only
  compatibility filter.
- Enforced normalized tenant checks before approval detail rendering, payload
  edits, status changes, auto-execution, and explicit HaloPSA execution.
- Scoped the approval embedded by `GET /workflow-runs/{run_id}` with the same
  normalized check: an out-of-scope approval is returned as `null` while the
  workflow-run response remains intact.
- Foreign approval IDs return 404. Legacy approvals without `client_id` remain
  accessible, and no-tenant installs retain list-all compatibility.
- Added endpoint and RBAC regression coverage for technician, admin, legacy,
  connector-execution behavior, workflow-run approval redaction, in-scope
  payload editing, and bound-tenant list scoping.

## Commands Run

- `pwd`, `git remote -v`, `git status --short --branch` — confirmed
  `W-A-I-T/wait-local-agent` on `ai/wla-wp20-approval-tenancy`, based on
  `origin/main`; no unrelated tracked changes were present.
- Verified `origin/main` at `94148ff` contains the merged #50, #51, and #52
  base, then reproduced the rebase in a writable temporary clone as rebased
  commit `3dd8cd5`. The workspace source tree matches that rebased tree.
- `git diff origin/main -- src/wait_local_agent/config.py
  src/wait_local_agent/rbac.py` — empty, as required.
- `.venv/bin/ruff check src tests` — passed.
- Targeted mypy on `api/app.py`, `config.py`, `rbac.py`, `tests/test_api.py`,
  and `tests/test_rbac.py` — passed with no issues.
- `git diff --check` and byte-for-byte comparison with the temporary rebased
  tree — passed.
- `timeout 500 .venv/bin/python -m pytest tests/ -p no:warnings --tb=short -q`
  — the final sandbox run produced no output and became unobservable before
  completion, so it was interrupted. This is recorded as a SANDBOX limitation
  only; no repository or dependency failure is inferred, and the expected two
  `tests/test_knowledge.py` environment-dependent failures were not confirmed
  in this sandbox.

## Files Touched

- `src/wait_local_agent/config.py`
- `src/wait_local_agent/rbac.py`
- `src/wait_local_agent/api/app.py`
- `tests/test_api.py`
- `tests/test_rbac.py`
- `ai/tasks/wla-wp20-approval-tenancy/implementation.md`
- `ai/tasks/wla-wp20-approval-tenancy/review.md`
- `ai/tasks/wla-wp20-approval-tenancy/status.json`

## Follow-Up

- Follow-up task required: `GET /tickets`, `POST /tickets/{ticket_id}/approvals`,
  `/audit` and its CSV exports, `/events`, `/reports`, `/collectors/runs`, and
  `GET /workflow-runs` still accept a caller-supplied `client_id` with no
  principal-derived check. Same vulnerability class as this task.
- Tenancy enforcement applies only to installs running with demo mode disabled
  and tokens configured; demo/untokened installs resolve to admin and ignore
  `WAIT_CLIENT_ID`. Worth stating in release notes.
- `_approval_client_scope` is intentionally kept separate from the
  smart-action scope helper because their unbound-principal semantics differ.
  A later cleanup could unify them if smart-action behavior is revisited.
- Human merge and deployment authority is unchanged.
