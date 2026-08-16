# Implementation — WLA-P2a2

## Chosen semantics

- Non-NULL `client_id` upserts use the v4 composite conflict target
  `(client_id, canonical_id)`. The same canonical ID can therefore be stored
  independently for different clients.
- NULL-client upserts preserve the legacy canonical-ID fallback. They update
  the first existing row for that canonical ID (retaining its existing client
  assignment), or create one NULL-client row when no row exists. Repeated
  NULL-client upserts therefore update one row rather than relying on SQLite's
  NULL-distinct composite uniqueness behavior.
- `get_canonical_asset_by_canonical_id(..., client_id=...)` is tenant-aware;
  callers that omit `client_id` retain the prior unscoped first-row behavior.

## Line-7267 caller decision

The `_asset_id_for_canonical_id` helper now accepts an optional client scope.
The `persist_collector_result` caller has the run's `client_id` available, so
it passes that scope for config snapshots, config diffs, and restore exercises.
The helper default remains `None` for other back-compatible callers.

## Implementation

- Added migration v4, `canonical_assets_tenant_unique`, with an ID-preserving
  `canonical_assets` rebuild, duplicate-pair guard, user-index recreation, and
  foreign-key verification.
- Re-added `Migration.foreign_keys_off`; the runner toggles SQLite foreign-key
  enforcement outside the transaction and restores the original state after
  commit or rollback.
- Updated canonical asset upsert and lookup paths in `store.py`.
- Added migration framework, rebuild-safety, tenant upsert/lookup, duplicate
  guard, and NULL-client regression tests; updated migration-version fixtures.
- Updated the changelog and client/connector tenancy concept documentation.

## Validation

- Focused regression gate: `8 passed` for the migration/framework, rebuild,
  tenant upsert/lookup, NULL-client, collector upsert-then-lookup, and updated
  migration tests.
- `mypy src tests`: `Success: no issues found in 208 source files`.
- `ruff check .`: `All checks passed!`.
- `bandit -r src`: `No issues identified` (0 high, 0 medium, 0 low issues).
- Migration rehearsal on a copy of a populated pre-v4 database: `canonical_assets
  2->2; asset_observations 1->1; ids [101, 205]->[101, 205];
  foreign_key_check=[]; foreign_keys=1`.
- The required full command
  `PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest
  tests/ -q --cov=wait_local_agent --cov-fail-under=95` was started twice but
  could not complete locally: it reached 43 passing tests and then stalled in
  the existing `test_connector_read_tools_reuse_existing_clients_and_tenant_scope`
  first `TestClient` POST. The same test stalled in isolation, and the
  faulthandler trace was in Starlette/AnyIO request handling. It was stopped
  with exit 130; therefore no full-suite 0-failed/coverage summary is claimed.
