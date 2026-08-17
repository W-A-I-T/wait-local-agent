# A-PR3b review notes

Scope reviewed: `src/wait_local_agent/store.py`, cursor/lease tests, migration
expectation updates, and ingestion documentation only.

The lease boundary is serialized per SQLite database connection with
`BEGIN IMMEDIATE`. The active-lease test is status-aware and treats a null
expiry on a legacy `syncing` row as stale. Claiming only changes status and
lease metadata, so cursor progress and historical successful-sync metadata are
preserved. Terminal writes require both `status = 'syncing'` and the exact
lease token, preventing a stale worker from changing its successor's row.

Public hydration uses an explicit projection of the six `SyncCursor` fields;
the internal lease columns are not part of the dataclass or API serialization.
The legacy upsert path takes the same write lock and raises a clear conflict
when it would overwrite an unexpired lease.

This review intentionally does not cover A-PR3a client changes or A-PR3c
adapters/poller behavior.
