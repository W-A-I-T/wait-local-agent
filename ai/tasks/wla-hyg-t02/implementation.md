# Implementation Notes

## Summary

- Enabled Ruff `RUF100` and `SLF` in the configured rule set.
- Added the requested `SLF001` per-file ignores for tests and scripts.
- Preserved the 26 blind-except rationales as plain comments and removed the
  six rationale-free `BLE001` directives.
- Restored the 45 existing source `SLF001` suppressions after the mandated
  standalone `--select RUF100 --fix` command treated configured rules as
  overridden, then added 20 reasoned source suppressions for newly exposed
  private-member accesses. The 19 legacy-collector reasons now state that the
  access delegates to the legacy collector module.
- Restored six live, line-level `E402` suppressions with reasons. The first
  employee-onboarding import also carries `I001` because the required reason
  makes that import exceed the 120-character line limit; the import itself was
  not reformatted.
- Removed all test/script `SLF001` directives and made no runtime behavior or
  dependency/API change.

## Commands Run

- `.venv/bin/ruff --version` -> `ruff 0.15.20`.
- `.venv/bin/ruff check --no-cache --select RUF100 --fix .` -> 375 fixes.
- `.venv/bin/ruff check --no-cache .` -> passed.
- `.venv/bin/ruff check --no-cache --extend-select RUF100 --statistics .` ->
  passed.
- The literal plan command
  `.venv/bin/ruff check --no-cache --select RUF100 --statistics .` reports 65
  `RUF100` findings because Ruff replaces, rather than extends, configured
  rule selection; after restoring the six live `E402` directives it reports 71.
  The configured full check and `--extend-select RUF100` check are the valid
  zero-finding forms.
- `rg` acceptance checks -> no `BLE001`; six expected line-level `E402`
  directives; no `SLF001` directives outside `src/`; 65 source `SLF001`
  directives.
- `.venv/bin/mypy src tests` -> passed, 327 source files.
- `.venv/bin/python -m pytest -q -x tests/test_api_import.py tests/test_config.py`
  -> 42 passed; two pre-existing dependency deprecation warnings.
- `git diff --check` -> passed.

## Round 2 Correction

- Removed the temporary file-level `E402` ignores from `pyproject.toml`.
- Restored the six line-level `E402` directives with the required rationale,
  preserving the actual late-import behavior.
- Replaced all 19 `# noqa: SLF001 - legacy` comments in `collectors.py` with
  `# noqa: SLF001 - delegates to the legacy collector module`.
- Re-ran Ruff, mypy, the focused tests, and `git diff --check`; all passed.

## Files Touched

- `pyproject.toml`
- `CHANGELOG.md`
- Comment-only directive cleanup in `scripts/*.py`, `src/**/*.py`, and
  `tests/**/*.py`.
- `ai/tasks/wla-hyg-t02/implementation.md`
- `ai/tasks/wla-hyg-t02/review.md`
- `ai/tasks/wla-hyg-t02/status.json`

## Follow-Up

- Claude should run the full repository suite and perform the final diff review.
- The required Kimi cross-family review was attempted with `kimi-code/k3` but
  failed before producing a verdict because the Kimi storage layer returned
  `storage write failed`; the blocker is recorded in `review.md` and
  `status.json`.
- The Claude final-gate prompt was generated from this task directory and is
  ready for the orchestrator.
- No PR was created; this handoff requested implementation on the existing
  task branch and retains human merge authority.

- 2026-09-03T23:53:53Z: Codex gpt-5.6-luna completed successfully; repository verification is next.

- 2026-09-03T23:55:27Z: Launching Codex gpt-5.6-luna implementation through the artifact runtime in /home/josephp/wla-work/wla-hyg-t02.

- 2026-09-04T00:04:33Z: Codex gpt-5.6-luna completed successfully; repository verification is next.
