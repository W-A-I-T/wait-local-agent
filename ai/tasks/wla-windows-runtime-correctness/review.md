# Review

## Changed Files

- Runtime: `platform_support.py`, `fs_permissions.py`, `observability.py`,
  `store.py`, `vault.py`, and `power_platform_deployment.py`.
- Tests: platform/filesystem/store permission tests plus observability, vault,
  and PAC deployment coverage.
- CI: `.github/workflows/test.yml` adds the scoped `backend-windows` job.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- SQLite pre-creation and WAL sibling restriction run during every `Store`
  construction; only a normal existing regular file is reopened.
- Windows ACL code is raw `ctypes` and could only be syntax/type reviewed here;
  the real DACL behavior needs the Windows CI job.
- `create_private_directory` intentionally hardens new directories only; it
  does not change permissions on an existing artifact root or vault parent.
- PAC command launching now has a `COMSPEC` wrapper only for Windows batch
  shims; logical audit evidence remains the PAC command and its arguments.
- Full release validation remains dependent on the project development
  environment and network access; the local aggregate run also hangs in the
  existing FastAPI `TestClient` health request.

## Version & Compatibility Evidence

- No dependency, SDK, API, or tooling version was added or changed by this
  task. The runtime target remains `requires-python >=3.12`.
- The working-tree `uv.lock` delta predates the coverage follow-up and matches
  the current dependency declarations, including PyInstaller `6.22.0`.
- `pip check` and `UV_CACHE_DIR=/tmp/wla-uv-cache uv lock --check --offline`
  passed. Online `pip-audit`/freshness verification was blocked by unavailable
  PyPI DNS, so CI remains authoritative for external-package compatibility.

## Open Questions

- Implementation questions are closed. Remaining gates are the first
  `backend-windows` run, the full 95% release validation, and the required
  cross-family/final review.

## Test Results

- Passed: targeted platform/filesystem/store coverage at 100% for both new
  modules, observability, config, PAC deployment, store, hardening AST, Ruff,
  full mypy, Bandit, `pip check`, lock consistency, public-surface, and diff
  checks.
- Not completed: full 95% suite, online pip-audit, UI npm validation, and real
  Windows execution. `tests/test_security_vault.py` is blocked by a local
  Starlette `TestClient` hang before assertions run.

## Diff Summary

- Artifact fallback no longer assumes POSIX flags and records tracebacks.
- New files, SQLite state, WAL siblings, vault files, and new artifact
  directories receive private permissions; vault replacements are atomic.
- PAC `.cmd`/`.bat` launches are safe and auditable on Windows.
- CI now exercises the Windows-aware test family without weakening the Ubuntu
  coverage gate.

## Requested Review Focus

- Verify Windows ACL application and the first CI run.
- Recheck SQLite initialization/reopen behavior and the command-evidence shape.
- Confirm the pre-existing `uv.lock` refresh is intentionally retained and no
  other unrelated repository changes appear before PR creation.
