# A-PR3c implementation — provider adapters and ingestion poller

Implemented the final A-PR3c slice on top of the merged A-PR3a read envelopes
and A-PR3b fenced cursor lease.

## Changes

- Added case-folded HaloPSA and ConnectWise ticket adapters. They preserve the
  provider response envelope, validate both remote identifiers before creating
  `Ticket` records, set `client_id` and `source_system` to `None`, and attach
  the polled connector instance ID.
- Added the synchronous `IngestionPoller` with injected client-builder,
  wall-clock, monotonic-clock, and sleeper seams. It enforces page/deadline/
  retry/lease bounds, maps atomic lease outcomes, retries transient provider
  failures with bounded `Retry-After`, and never emits provider exception text
  to audit.
- Added the pragmatic fencing point immediately before each non-empty page's
  `ingest_provider_tickets` call. A lost lease stops further writes; at most one
  already in-flight page can be corrected on the next full idempotent sweep.
- Changed provider-ticket sink audit detail to a static message plus the
  internal ticket ID; provider subjects are no longer copied into unredacted
  audit records.
- Added adapter/poller tests covering field bridges, pagination signatures,
  dropped-row continuation, status taxonomy, idempotent re-poll, lock skip,
  bounds, fencing, and audit redaction.

No route, scheduler job, migration, commit, or push was added in A-PR3c.
