# Implementation Notes

## Summary

- Implemented the Windows runtime correctness contract across artifact writes,
  private storage, vault persistence, SQLite initialization, PAC batch shims,
  and CI coverage.
- Added `platform_support.py` for monkeypatchable platform predicates and
  `fs_permissions.py` as the single owner of POSIX modes and Windows ACL
  application.
- Preserved logical PAC command evidence while launching `.cmd`/`.bat` files
  through `COMSPEC`, with shell-metacharacter rejection on stage and rollback
  paths.
- Completed the coverage follow-up without widening pragmas: both foundation
  modules are at 100% statement and branch coverage in the focused run.
- Kept `reports/hardening_checks.py`, desktop code, UI, and migrations
  unchanged. The pre-existing working-tree `uv.lock` refresh was preserved and
  checked against the current `pyproject.toml`; this task added no dependency
  declaration or API change.

## Commands Run

- `ruff check .`, `mypy src tests`, and `bandit -r src`: passed.
- Focused foundation coverage: 24 passed; `platform_support.py` and
  `fs_permissions.py` each measured at 100% statement and branch coverage.
- Focused runtime tests: observability (44), config (22), and PAC deployment
  (47) passed, as did the new platform/filesystem/store tests.
- `tests/test_store.py` and `tests/test_hardening_checks.py`: passed.
- `python scripts/public_surface_audit.py`, `git diff --check`, and
  `python -m pip check`: passed.
- `UV_CACHE_DIR=/tmp/wla-uv-cache uv lock --check --offline`: passed. No
  dependency or API version was changed by this task; online freshness/audit
  remains unavailable because PyPI DNS is blocked here.
- `scripts/validate_release.sh`: stopped at `pip-audit` because `pypi.org`
  could not be resolved; the preceding Ruff, mypy, and Bandit steps passed.
- Full pytest with the 95% gate: bounded run timed out after 180 seconds. The
  first security-vault test hangs in Starlette `TestClient` request handling;
  its faulthandler trace is in the AnyIO portal, not a failing assertion.
- UI npm validation was not run because `ui/node_modules` is absent.

## Files Touched

- `.github/workflows/test.yml`
- `src/wait_local_agent/platform_support.py`
- `src/wait_local_agent/fs_permissions.py`
- `src/wait_local_agent/observability.py`
- `src/wait_local_agent/store.py`
- `src/wait_local_agent/vault.py`
- `src/wait_local_agent/power_platform_deployment.py`
- `tests/test_platform_support.py`, `tests/test_fs_permissions.py`,
  `tests/test_store_permissions.py`
- `tests/test_observability.py`, `tests/test_security_vault.py`,
  `tests/test_power_platform_deployment.py`
- `ai/tasks/wla-windows-runtime-correctness/{implementation.md,review.md,status.json}`

## Follow-Up

- GitHub must run the new `backend-windows` job on `windows-latest` to validate
  real Windows ACL and batch-shim behavior; this Linux checkout cannot do so.
- Re-run the full release validator in an environment with PyPI access and a
  non-hanging compatible FastAPI/Starlette test environment, then complete the
  required cross-family and final reviews.
