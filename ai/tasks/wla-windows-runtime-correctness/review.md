# Review

## Changed Files

- Runtime: `platform_support.py`, `fs_permissions.py`, `observability.py`,
  `store.py`, `vault.py`, and `power_platform_deployment.py`.
- Tests: platform/filesystem/store permission tests plus observability, vault,
  config, and PAC deployment coverage.
- CI: `.github/workflows/test.yml` adds the scoped `backend-windows` job.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- SQLite pre-creation and WAL sibling restriction run during every `Store`
  construction; only a normal existing regular file is reopened.
- Windows ACL code uses explicit pointer-sized ctypes signatures, but the real
  DACL behavior still needs the Windows CI job.
- Directory ACL failures are deliberately logged and non-fatal after successful
  directory creation, preserving artifact recording under degraded ACL setup.
- `create_private_directory` intentionally hardens new directories only; it
  does not change permissions on an existing artifact root or vault parent.
- Temporary artifact/key files are closed before cleanup; Windows cleanup also
  tolerates `PermissionError` when a failed operation leaves a sharing lock.
- PAC command launching now has a `COMSPEC` wrapper only for Windows batch
  shims; logical audit evidence remains the PAC command and its arguments.
- Full release validation remains dependent on the project development
  environment and network access; the local aggregate run also hangs in the
  existing FastAPI `TestClient` health request.

## Version & Compatibility Evidence

- No dependency, SDK, API, or tooling version was added or changed by this
  task. The runtime target remains `requires-python >=3.12`.
- No dependency declaration, lockfile, or package/API version changed in this
  follow-up; the runtime remains Python `>=3.12` and the existing PyInstaller
  pin remains unchanged.
- `pip check` passed. Offline lock checking could not resolve an uncached
  `apscheduler` artifact for a non-active Python/platform split, and
  `pip-audit` could not resolve `pypi.org`; CI remains authoritative for
  external-package compatibility.

## Open Questions

- Implementation questions are closed. Remaining gates are the first
  `backend-windows` run, the full 95% release validation in a compatible
  environment, and the required cross-family/final review.

## Test Results

- Passed: 140 targeted Windows-aware tests; 5 vault-only tests; 100% focused
  statement/branch coverage for both foundation modules; Ruff, mypy, Bandit,
  `pip check`, public-surface, and diff checks.
- Not completed: full 95% suite, online `pip-audit`, real Windows execution,
  and cross-family review. UI validation was run separately and passed: 232
  tests and the production build.
  `tests/test_security_vault.py` is blocked at its first API test by a local
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
- Confirm no dependency or lockfile changes appear before PR creation.

## Blocker — cross-family review unavailable

The required Kimi cross-family review could not run: the provider returned
HTTP 403, "You've reached your usage limit for this billing cycle."

No substitute reviewer was used. Standing workflow policy requires recording
the blocker and returning ownership to the human rather than swapping in
another provider.

This remains an external release gate after the Windows-CI follow-up. The
current implementation evidence is recorded above; the local release script
still stops at network-dependent `pip-audit`, and the aggregate suite cannot
complete because the first API test hangs in the local Starlette environment.
PR #404 remains open and must not merge until this review and the real
Windows-CI run complete or are explicitly waived.
