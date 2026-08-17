# A-PR3b implementation — fenced store poll lease

Implemented only the A-PR3b store boundary from the adapter/poller plan.

## Changes

- Registered migration v6, `poll_lease`, adding nullable `lease_token` and
  `lease_expires_at` columns to `sync_cursors` additively with foreign keys
  intact.
- Added `PollLeaseClaimResult` with `granted`, `locked`, and `instance_missing`
  outcomes. Claims use one `BEGIN IMMEDIATE`, preserve cursor progress, and
  take over expired or legacy null-expiry syncing rows.
- Added token-fenced terminal release. A stale token cannot modify a successor;
  lease columns are cleared on release and non-clean finishes preserve the
  caller-supplied historical `last_synced_at`.
- Guarded `upsert_sync_cursor` against overwriting a live lease.
- Replaced every public cursor `select *` with an explicit six-column public
  projection. Lease columns are never hydrated into `SyncCursor` or returned by
  the ingestion endpoint.
- Added migration, concurrency, stale takeover, fencing, preservation,
  hydration, endpoint, and live-upsert-guard tests.

Adapters, the poller, routes, and scheduler work are intentionally not included.

## Validation

Validation results are recorded in the handoff response after the focused and
project-wide checks are run. No commit or push was made.
