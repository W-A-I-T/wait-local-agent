# A-PR3c review notes

Scope reviewed: provider adapters, synchronous ingestion poller, and the small
provider-subject audit leak fix in the existing sink.

The adapter registry is case-folded and uses Halo's positional pagination and
ConnectWise's keyword-only pagination. Both adapters validate trimmed remote
ticket and company identifiers before constructing records and preserve the
store invariants (`client_id=None`, `source_system=None`, and the polled
`connector_instance_id`).

The poller treats only a ready HTTP 2xx empty raw page as EOF. Raw pages with
all rows dropped continue and make degradation sticky. It classifies blocked,
throttled, timeout/connect, 408, and 5xx conditions as degraded; malformed,
redirect, configuration/auth, inactive-instance, and sink-invariant failures
as failed; and a clean verified EOF as idle. Lease release is best-effort and
occurs before the static audit event.

The pragmatic fence revalidates the exact unexpired token immediately before
each page write. A stale worker therefore performs no subsequent writes; one
page already in flight can be corrected by the next full idempotent sweep.
Atomic token fencing inside the sink remains intentionally deferred to A-PR6.
