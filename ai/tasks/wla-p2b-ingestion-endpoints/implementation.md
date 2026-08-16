# Implementation

Implemented the P2b ingestion operator endpoint slice over the existing P2a
store accessors. No poller, provider fetch, schema change, UI change, or store
accessor change was made.

## Routes

- `GET /ingestion/sync-cursors`: MSP operator-only cursor listing.
- `GET /ingestion/unmapped`: scope-aware quarantine listing with the existing
  `connector_instance_id` filter and `ValueError`-to-400 mapping.
- `POST /ingestion/unmapped/{record_id}/resolve`: MSP operator-only review
  resolution, returning 404 when the store accessor returns no record.

The routes reuse `AdminAccess`, `ViewerAccess`, `_require_msp_operator`, and
`resolve_client_scope` from the existing API. Dataclass responses use `asdict`.

## Validation

- `ruff check .`: passed (`All checks passed!`).
- `/home/josephp/wait-local-agent/.venv/bin/mypy src tests`: passed
  (`Success: no issues found in 209 source files`). The exact host `mypy src
  tests` command could not resolve the installed `slowapi` dependency and
  reported five import-not-found errors.
- `/home/josephp/wait-local-agent/.venv/bin/bandit -r src`: passed (`No issues
  identified`, 0 high/medium/low issues). The exact host `bandit -r src`
  command was unavailable on `PATH`.
- Surface-manifest test and JSON/diff checks passed.
- Exact required pytest command:

  ```text
  PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/ -q --cov=wait_local_agent --cov-fail-under=95
  ```

  It emitted 43 passing-test dots, then stalled in the repository's existing
  Starlette TestClient lifespan behavior. The same stall reproduces in the
  existing P1 TestClient smoke test, so the run was interrupted with exit
  130. No pytest summary line, coverage percentage, or successful exit 0 was
  produced. The focused P2b test has the same environment-level stall.
