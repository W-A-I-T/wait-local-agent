# Implementation — WLA-P2b1

## Scope

- Backend-only implementation on `codex/wla-p2b1-reconcile` in
  `W-A-I-T/wait-local-agent`.
- No provider fetch, scheduler, connector-instance-to-provider-client bridge,
  migration, UI change, commit, or push was made.

## Implementation

- Added `Store.ingest_tickets`, returning `IngestSummary(written,
  quarantined)` for future poller callers.
- Routed `ingest_ticket_file` through the reusable method while preserving its
  existing `int` count return.
- Tickets with no explicit client and effective connector provenance plus an
  external company ID resolve only through `resolve_client_for`. A verified
  result is written with the resolved client; no result is quarantined and the
  ticket is not written.
- Explicit-client tickets and tickets without connector provenance retain the
  existing write path, including local/demo ingestion.

## Quarantine deduplication

Deduplication is implemented in `record_unmapped`, rather than by changing the
existing schema. Before inserting, it checks for an unresolved row with the
same `(connector_instance_id, external_id, record_type)` key and returns that
row when present. The check and insert run in a `BEGIN IMMEDIATE` transaction,
so repeated unresolved ingestion reuses one open quarantine entry. If an old
entry has been marked resolved, a later unresolved occurrence may create a new
review entry. The ticket payload digest is the SHA-256 of canonical,
sorted-key JSON for the received ticket.

## Files

- `src/wait_local_agent/models.py`
- `src/wait_local_agent/store.py`
- `tests/test_wla_p2b1_reconcile.py`
- `docs/concepts/clients-and-connectors.md`
- `CHANGELOG.md`
- `ai/tasks/wla-p2b1-reconcile/implementation.md`

## Validation

- Focused regression command:

  ```text
  PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/test_wla_p2b1_reconcile.py tests/test_wla_p2_provenance.py -q
  .........                                                                [100%]
  9 passed
  ```

- Supplied environment `mypy`:

  ```text
  /home/josephp/wait-local-agent/.venv/bin/mypy src tests
  Success: no issues found in 210 source files
  ```

- `ruff check .`:

  ```text
  All checks passed!
  ```

- Supplied environment `/home/josephp/wait-local-agent/.venv/bin/bandit -r
  src`:

  ```text
  No issues identified.
  Total issues (by severity): Undefined: 0, Low: 0, Medium: 0, High: 0
  ```

- The exact required full-suite command was run without creating a venv:

  ```text
  PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/ -q --cov=wait_local_agent --cov-fail-under=95
  ...........................................
  interrupted with exit 130 after 43 passing-test dots; no pytest summary or coverage percentage emitted
  ```

  It stalled in the repository's existing FastAPI `TestClient` path after the
  same 43 tests documented by prior slices. Therefore the mandatory full-suite
  `0 failed`, `>=95%`, and exit-0 gate is not claimed here.

- The exact host `mypy src tests` command reports five pre-existing missing
  `slowapi`/`slowapi.*` imports. The supplied environment command above is
  clean. The exact host `bandit -r src` command is unavailable on `PATH`; the
  supplied environment bandit command is clean.
