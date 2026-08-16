# Implementation — `wla-s0-pr3a-upsert-ownership`

## Delivered contract

- Added an ownership guard in `Store.ingest_provider_tickets` immediately after
  the composite-key lookup and before the existing upsert.
- A conflicting persisted owner is left untouched; the provider payload is
  recorded as an `ownership_conflict` unmapped record and counted as
  quarantined.
- New rows and same-owner re-polls retain the existing upsert, status-history,
  and audit behavior.
- Added store-level regression coverage for cross-owner contamination,
  same-owner content updates, and new-row insertion.

## Files

- `src/wait_local_agent/store.py`
- `tests/test_wla_s0_upsert_ownership.py`
- `CHANGELOG.md`
- `ai/tasks/wla-s0-pr3a-upsert-ownership/implementation.md`
- `ai/tasks/wla-s0-pr3a-upsert-ownership/review.md`

## Validation record

- `PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/test_wla_s0_upsert_ownership.py -q`
  → `...                                                                      [100%]` (exit 0).
- `mypy src tests` → five `import-not-found` errors for `slowapi` and its
  submodules in `src/wait_local_agent/api/app.py` (exit 1); the bare mypy
  interpreter lacks the installed project dependency.
- `/home/josephp/wait-local-agent/.venv/bin/mypy src tests` → `Success: no
  issues found in 216 source files` (exit 0).
- `ruff check .` → `All checks passed!` (exit 0).
