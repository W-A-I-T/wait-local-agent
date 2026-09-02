# Implementation — wla-pac-shim-tests

Status: implemented; awaiting orchestrator review and commit.

## Diff by file

- `tests/power_platform_support.py`: added `write_pac_shim`, which writes a
  real executable POSIX shim or a Windows `.cmd` launcher plus its shared
  Python implementation. The shim records argv and cwd, reports PAC 2.4.1
  for `help`, writes a real ZIP for `solution pack`, and has a deterministic
  non-zero failure trigger. Its redaction probe keeps `token=` and
  `authorization=` field names but uses an obviously fake value that does not
  match credential scanners, avoiding a gitleaks finding across all refs while
  retaining the raw-value-absent and `[redacted]` assertions.
- `tests/test_power_platform_deployment.py`: added real-subprocess coverage
  for exact pack argv including `--packagetype Unmanaged`, workspace cwd,
  version-floor enforcement, real ZIP digest validation, non-zero failure, and
  stdout/stderr redaction. The `pac help` version probe intentionally does not
  set `cwd` and may inherit the process working directory; only stage command
  invocations are confined to the configured workspace. The autouse version
  stub is bypassed only for these shim-backed tests; timeout and OSError tests
  retain injected runners.
- `src/wait_local_agent/power_platform.py` and
  `src/wait_local_agent/power_platform_deployment.py`: construct solution ZIP
  paths with `pathlib.Path` so emitted argv uses the host platform separator
  and still round-trips through the existing artifact validation. The mixed
  separator Windows bug was found by the real-subprocess shim test; the old
  fake-runner tests could not expose it.

The module docstring states the boundary explicitly: these tests prove the
execution path and nothing about Dataverse; a shim is not a tenant.

## Validation

- `ruff check .`: passed.
- `git diff --check`: passed.
- `mypy src tests`: existing environment limitation; six missing `slowapi`
  stubs in `src/wait_local_agent/api` prevent a repository-wide pass. No
  changed-file type errors were reported before those errors.
- `pytest`: not run, as required by the task instructions.
- The real PAC binary was not invoked; only the test-created shim is used.

No PR was created because this linked worktree is orchestrator-managed; the
orchestrator retains commit, push, and merge authority.
