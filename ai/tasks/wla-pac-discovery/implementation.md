# Implementation — wla-pac-discovery

Status: implemented; awaiting required cross-family and final-gate review.

## Diff by file

- `src/wait_local_agent/config.py`: added optional `Settings.pac_path` and
  loaded `WAIT_PAC_PATH`, treating an empty value as unset.
- `src/wait_local_agent/power_platform.py`: added explicit-path/PATH resolver,
  bounded injectable `pac help` version probe, version parsing, integer-tuple
  comparison, and version-inclusive CLI status output. Corrected the status
  metadata so `commands_executed` is true exactly when the resolved executable
  triggered the bounded version probe, and updated its docstring accordingly.
- `src/wait_local_agent/power_platform_deployment.py`: replaced stage and
  rollback binary lookup with the resolver; added post-availability minimum
  version and unknown-version blocking; preserved existing gates and command
  execution logic.
- `src/wait_local_agent/api/app.py`: replaced the approval advisory lookup with
  the resolver and added the configured-invalid-path message.
- `tests/test_power_platform.py`: added resolver, `pac help` version-probe, and
  integer comparison tests; the injected runner pins the exact probe argv.
- `tests/test_power_platform_deployment.py`: added stage/rollback version gate
  and runner-never-called tests, at/above-floor success coverage, and faked all
  version probes in existing execution tests.
- `docs/consultant/consultant-power-platform-deployment.md`: documented
  `WAIT_PAC_PATH`, the common dotnet-tool location, symlink restriction, and
  version blocking behavior.
- `CHANGELOG.md`: added the requested Added and Fixed entries.
- `ai/tasks/wla-pac-discovery/{implementation.md,review.md,status.json}`:
  recorded implementation, review state, and current gates.

## Deviations

None. The plan-listed files only were changed; blocked paths were untouched.
No dependency, route, approval, evidence, digest, promotion, or rollback-policy
changes were made.

## PAC version probe correction

`pac_cli_version` intentionally invokes `[executable, "help"]`. This argv was
verified against the real `pac` 2.4.1 binary: `pac help` prints the `Version:`
line and exits 0, while `pac --version` prints its banner, reports `Not a valid
command`, and exits 1. The regression test pins the injected runner argv, and
tests do not invoke the real binary.

## Gate results

`git diff --check`

No output; passed.

`ruff check .`

```text
All checks passed!
```

Targeted static typing:

`mypy src/wait_local_agent/config.py src/wait_local_agent/power_platform.py src/wait_local_agent/power_platform_deployment.py tests/test_power_platform.py tests/test_power_platform_deployment.py`

```text
Success: no issues found in 5 source files
```

Repository-wide typing:

`mypy src tests`

```text
src/wait_local_agent/api/auth_routes.py:12: error: Cannot find implementation or library stub for module named "slowapi"  [import-not-found]
src/wait_local_agent/api/app.py:24: error: Cannot find implementation or library stub for module named "slowapi"  [import-not-found]
src/wait_local_agent/api/app.py:25: error: Cannot find implementation or library stub for module named "slowapi.errors"  [import-not-found]
src/wait_local_agent/api/app.py:25: error: Cannot find implementation or library stub for module named "slowapi.extension"  [import-not-found]
src/wait_local_agent/api/app.py:26: error: Cannot find implementation or library stub for module named "slowapi.middleware"  [import-not-found]
src/wait_local_agent/api/app.py:27: error: Cannot find implementation or library stub for module named "slowapi.util"  [import-not-found]
src/wait_local_agent/api/app.py:25: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
Found 6 errors in 2 files (checked 322 source files)
```

`pytest`: not run, as required by the task contract because this sandbox hangs
on this repository's FastAPI `TestClient` fixtures. The tests use only fakes;
the real `pac` binary was not invoked.

## CI Bandit fix

The system `bandit` executable was unavailable, so the scan used the existing
local WLA virtualenv's Bandit installation:

`PATH=/home/josephp/wait-local-agent/.venv/bin:$PATH bandit -r src`

Result: passed with exit 0; Bandit reported `No issues identified.` It did not
report B603 for the `pac_cli_version` probe, so no call-site suppression was
added.
