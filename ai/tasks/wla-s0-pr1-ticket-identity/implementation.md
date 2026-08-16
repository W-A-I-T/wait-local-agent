# Implementation — S0-PR1

## Delivered contract

- Added migration v5, `ticket_identity_and_tenancy`, after v4 with
  `foreign_keys_off=True`. It is self-sufficient on the six-column legacy
  ticket schema, backfills the client directory before rebuilding the ticket
  table, trims key provenance, aborts on duplicate composite keys, preserves
  every ticket ID and row, recreates indexes, and checks both foreign keys and
  SQLite integrity before returning.
- Added `tickets.client_id` `NOT NULL REFERENCES clients(client_id)` and the
  partial unique index on `(connector_instance_id, external_id)`.
- Added `last_seen_at` and `occurrence_count` to `unmapped_records`, including
  migration backfill, row mapping, repeated-occurrence updates, and model
  fields.
- Split local and provider ingestion. Local/file/CLI ingestion requires an
  explicit active client, rejects any connector provenance, writes
  `source_system='local'`, and refuses cross-client or connector-row takeover.
  Provider ingestion validates the active instance, active verified mapping,
  instance/client consistency, and all provenance in one transaction.
- PR1's unmapped seam is `record_unmapped` only: it increments `quarantined`
  and creates no quarantine ticket. S0-PR2 owns the quarantine-ticket write.

## S0-PR1 fallout reconciliation

- Added shared `tests.support.ensure_test_client` / `ensure_test_clients`
  helpers and updated direct ticket, chat, action, MCP, end-user, analytics,
  and cross-client fixtures to create active client-directory rows before
  writing FK-backed records.
- Reconciled mixed-tenant local-ingest coverage to call the explicit local
  writer once per tenant. Quarantine-backed fixtures now use the reserved
  `__quarantine__` client instead of attempting impossible NULL writes.
- Updated migration expectations to include v5 and count six migrations, and
  added targeted coverage for legacy-client backfill, the v5 rebuild/index and
  duplicate guard, the SQLite-version guard, tenant-scoped knowledge fixtures,
  and end-user validation paths.
- No production tenancy constraint, migration ordering, identity algorithm,
  provenance validation, or active-client validation was weakened.

## Compatibility choices

SQLite `RETURNING id` is used for the provider composite-key upsert, with a
runtime `sqlite3.sqlite_version_info >= (3, 35, 0)` assertion in `Store`.
The provider path preselects status/client by composite key before the upsert
and uses the returned persisted ID for status history and audit.

`WAIT_TICKET_NS` is the frozen literal
`7ab19543-3db8-506a-af8c-341787eb5cdc`, derived once from
`uuid.NAMESPACE_URL` and `wait-local-agent:ticket-identity:v1`. Provider input
IDs are ignored. The UUID name is JSON encoded as
`[trimmed_connector_instance_id, trimmed_external_id]` with compact separators
and `ensure_ascii=False`; normalization is trim-only and case-sensitive.

## Files

Backend-only changes cover `src/wait_local_agent/store.py`,
`src/wait_local_agent/models.py`, `src/wait_local_agent/cli.py`, the updated
test callers plus `tests/support.py`, migration/provenance tests, the local
demo scripts and docs, `CHANGELOG.md`, and this task report. No `ui/` path was
changed.

## Validation record

- Focused migration/provenance regression command:
  `PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/test_store.py tests/test_wla_p2_provenance.py tests/test_wla_p2b1_reconcile.py -q`
  → `................................. [100%]` (34 passed, exit 0).
- `mypy src tests` → `Success: no issues found in 212 source files` (exit 0).
- `ruff check .` → `All checks passed!` (exit 0).
- `bandit -r src` → `No issues identified.`; 71 pre-existing `# nosec`
  suppressions reported, no high/medium/low findings (exit 0).
- Populated-copy rehearsal:
  `ids_preserved=True before_ids=1 after_ids=2`,
  `nulls_to_quarantine=1`, `foreign_key_check=[]`, `integrity_check=ok`,
  `row_count_before=2 row_count_after=2`, `index_present=True` (exit 0).
- Duplicate preflight rehearsal raised exactly:
  `tickets contains duplicate (connector_instance_id, external_id) pairs: [('instance-a', 'remote-a', 2)]`.
- The mandated full command was invoked exactly as specified:
  `PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/ -q --cov=wait_local_agent --cov-fail-under=95`.
  It did not complete: the installed FastAPI 0.139.0 / Starlette 1.3.1 /
  httpx 0.28.1 test client hangs even on a minimal one-route FastAPI smoke
  test, so the command was interrupted with exit 130 before a coverage
  summary. No failed assertion summary was produced; the required 0-failed /
  >=95% gate therefore remains unverified in this environment.
- All runnable non-`TestClient` tests pass after reconciliation. The exact
  full command still stalls on the installed FastAPI 0.139.0 / Starlette 1.3.1 /
  httpx 0.28.1 stack before the first HTTP request; a minimal FastAPI smoke
  request reproduces the same hang. This is an environment dependency blocker,
  not a tenancy assertion failure.
