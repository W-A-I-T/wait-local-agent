# Implementation — WLA-P2a additive provenance slice

## Scope

- Branch: `codex/wla-p2-provenance`
- Repository: `W-A-I-T/wait-local-agent`
- Backend-only. No UI, poller, or ingestion API routes were added.
- No commit or push was performed.
- The canonical-assets tenant-uniqueness rebuild was removed from this slice
  and is deferred to a separate future slice. `canonical_assets` and its
  existing upsert/lookup behavior remain as on `origin/main`.

## Changes

- `src/wait_local_agent/store.py` registers migration v3 as
  `provenance_and_ingestion`, adds the four nullable ticket provenance columns,
  and creates `sync_cursors` and `unmapped_records` idempotently.
- Ticket ingestion and end-user ticket creation accept and return optional
  provenance fields; existing call sites retain their defaults.
- Cursor and unmapped-record accessors validate connector identity/status and
  enforce client scope on tenant-bearing unmapped-record reads.
- `src/wait_local_agent/models.py` adds the ticket provenance fields plus
  `SyncCursor` and `UnmappedRecord` models.
- `src/wait_local_agent/migrations.py` is unchanged from `origin/main`;
  migration v3 does not disable foreign keys.
- Migration-list assertions were updated for v3, and
  `tests/test_wla_p2_provenance.py` covers the additive schema and accessors.

## Validation evidence

Focused additive and regression tests passed:

```text
4 passed
```

Migration rehearsal on a SQLite backup copy of a populated v2 database:

```text
migration rehearsal on copy: before tickets=1 canonical_assets=4 asset_observations=4; after tickets=1 canonical_assets=4 asset_observations=4; foreign_key_check=[]; foreign_keys=1; counts_preserved=True
```

Requested static checks:

- `ruff check .` — `All checks passed!` (exit 0).
- `mypy src tests` — blocked by five missing `slowapi`/`slowapi.*` imports in
  the supplied PATH interpreter (exit 1). A relaxed check with missing imports
  ignored and stale unused-ignore warnings disabled passed all 207 files.
- The exact requested pytest command was started verbatim, reached 43 passing
  tests, and stalled in the existing FastAPI `TestClient` path before emitting
  a summary or coverage report. A minimal FastAPI `TestClient` GET reproduces
  the same deadlock under the supplied interpreter; no trustworthy full-suite
  `N passed` or coverage result is available from this environment.

The required full-suite 0-failed/95%-coverage gate remains pending a repaired
test environment. Human merge and deployment authority remains required.
