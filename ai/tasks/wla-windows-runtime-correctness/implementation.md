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
- Fixed the Windows-CI follow-up defects: all Win32 pointer/handle calls now
  have explicit ctypes signatures, ACL hardening failures are logged and
  non-fatal during directory creation, and temporary-file cleanup tolerates
  Windows sharing/permission errors after closing descriptors.
- Made the scoped Windows test files portable for Windows path rendering,
  unavailable descriptor-relative flags, and non-POSIX permission semantics.
- Completed the remaining Windows test-portability follow-up: POSIX chmod error
  assertions now inject the POSIX backend explicitly, and default configured
  paths are compared as `Path` values instead of separator-sensitive strings.
- Kept `reports/hardening_checks.py`, desktop code, UI, and migrations
  unchanged. No dependency declaration, lockfile, or version/API contract was
  changed by this task.

## Commands Run

- `ruff check .`, `mypy src tests`, and `bandit -r src`: passed.
- Focused foundation coverage: 26 passed; `platform_support.py` and
  `fs_permissions.py` each measured at 100% statement and branch coverage.
- Focused Windows-aware runtime tests: 140 passed across observability,
  config, PAC deployment, platform support, filesystem permissions, and store
  permissions.
- Follow-Up 3 focused suite: 141 passed across the same Windows-aware modules;
  the specifically changed vault regression test also passed independently.
- Vault-only tests that do not construct the hanging API client: 5 passed.
- `python scripts/public_surface_audit.py`, `git diff --check`, and
  `python -m pip check`: passed.
- `scripts/validate_release.sh`: stopped at `pip-audit` because `pypi.org`
  could not be resolved; the preceding Ruff, mypy, and Bandit steps passed.
- `uv lock --check --offline`: could not resolve the uncached `apscheduler`
  artifact for another supported Python/platform split; no lockfile or
  dependency declaration changed.
- Commit/push was not completed in this managed checkout: the shared worktree
  Git index is read-only, and the isolated Git push path could not resolve
  `github.com`. The final three test fixes remain present and verified locally.
- Full pytest with the 95% gate: blocked by the first API test,
  `test_api_auth_demo_mode_allows_local_demo_without_token`, hanging in the
  local Starlette `TestClient`/AnyIO portal before an assertion.
- UI validation was not reached by the release script after the network-gated
  `pip-audit` step.

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
  `tests/test_power_platform_deployment.py`, `tests/test_config.py`
- `ai/tasks/wla-windows-runtime-correctness/{implementation.md,review.md,status.json}`

## Follow-Up

- GitHub must run the new `backend-windows` job on `windows-latest` to validate
  real Windows ACL and batch-shim behavior; this Linux checkout cannot do so.
- Re-run the full release validator in an environment with PyPI access and a
  non-hanging compatible FastAPI/Starlette test environment.
- The required cross-family review remains unavailable as recorded in
  `review.md`; no substitute reviewer was used.
