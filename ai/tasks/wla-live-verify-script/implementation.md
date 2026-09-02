# Implementation — wla-live-verify-script

## Summary

- Added `scripts/verify_power_platform_live.sh` as the release-time operator
  procedure for the real Power Platform boundary.
- Added fail-fast PAC, auth-profile, workspace, write-gate, target-URL, and
  WAIT CLI preconditions.
- Routed the product path through the verified CLI subcommands `microsoft
  package build`, `validate`, and `materialize`.
- Made the materialization result's `pac_plan.commands` the sole source of the
  PAC pack argv. The script does not hardcode the pack arguments.
- Added exact `files[]` versus on-disk pollution checking, explicit import and
  solution-list verification, printed cleanup guidance, and the required
  non-proven claims block.
- Added the backend workflow syntax-only check, deployment documentation, and
  an append-only live-verification receipt seeded from the prior recorded run.

## Safety boundaries

- The script never invokes `pac solution delete` or otherwise deletes a tenant
  solution.
- It stages package input into a fresh temporary directory below the
  pre-existing WAIT workspace and removes only that local temporary directory
  on exit.
- It does not reject `partial_source`; it prints the package status and every
  design-only reason verbatim.
- No `pac` command, live-verification script run, or `pytest` run was performed
  during this implementation.

## Validation

- `bash -n scripts/verify_power_platform_live.sh` — passed.
- `ruff check .` — passed (`All checks passed!`).
- `mypy src tests` — ran and reported the repository's existing six missing
  `slowapi`/`slowapi.*` stubs in `src/wait_local_agent/api`; no new script
  typing was involved.
- `pytest` was not run as required.
- `pac` and the live-verification script were not run as required.
- `git diff --check` — passed for tracked changes; targeted new files contain
  no trailing whitespace.

Full runtime/live validation remains an operator release task.
