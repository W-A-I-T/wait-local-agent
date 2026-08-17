# Clients and connector instances

WAIT keeps client identity separate from provider configuration. The local
client directory is the authority for which organizations the runtime knows
about. Existing tickets and discovered assets continue to use their current
storage and behavior; v5 preserves existing ticket IDs while backfilling
legacy ownership into this directory before tenant enforcement.

## Client directory

Each client has a name and a lifecycle status: active, archived, or
quarantine. The reserved **Unmapped / Quarantine** entry is created when the
runtime starts. It gives ingestion a visible, reviewable destination for
legacy tickets whose ownership is blank. Non-blank legacy ticket client IDs
are backfilled as active directory entries when needed.

The directory is tenant-scoped. A bound client principal can see only its
own client records. MSP operators and the local demo can use the operator
directory view. Creating clients and changing their status remains an
operator-only action.

## Connector instances

A connector instance represents one configured provider connection, such as a
HaloPSA, ConnectWise, NinjaOne, or Microsoft 365 estate. An instance may be
shared at the MSP level or associated with one client. Its credential field is
only a reference to the existing local vault; credentials are not stored in
the connector directory. Non-secret connection settings are kept separately
from that reference.

The existing boot-time Settings connector configuration remains in place. A
provider ingest must name one active connector instance, and the instance's
connector type supplies the stored source-system value.

The connector factory is the guarded bridge between an active instance and a
provider read client. It reads only the referenced vault record, requires the
provider's exact credential schema, copies only that instance's provider
settings into a sanitized read-only `Settings` container, and fails closed for
inactive instances, malformed configuration, or missing credentials. Each
configured API origin is checked against `WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS`;
outbound requests then use DNS-pinned transport with globally routable-address
checks. HaloPSA derives and validates its token endpoint from the API origin,
so an instance cannot redirect its OAuth secret to another allowlisted host.

The synchronous ingestion poller uses this factory for one active instance at a
time. The factory itself still does not start polling, schedule work, or write
provider records.

## Verified mappings

A mapping links an external company identifier from one connector instance to
a WAIT client. New mappings start as unverified. An operator must verify a
mapping before it can resolve provider records to a client, and the runtime
allows at most one verified mapping for a given external company within one
connector instance. Multiple unverified candidates can remain available for
review.

If there is no verified, unambiguous mapping, later ingestion should resolve
the record to no client and place it in the quarantine path. This keeps
identity decisions explicit and prevents an arbitrary provider company from
crossing a tenant boundary.

The Clients, Connector Instances, and Client-Connector Mappings API routes
are administrative and tenant-scoped surfaces. They are not a replacement for
the approval and write gates used by provider actions.

## Provenance and ingestion groundwork

Tickets can carry optional provenance: the source system, connector instance,
remote ticket ID, and remote company ID. These fields do not replace the local
ticket identity or make a client assignment trustworthy by themselves. A
ticket without connector provenance remains a local record, and an existing
ticket can continue to have no client assignment.

The local ingestion ledger records a cursor for each connector and record
kind. The synchronous poller claims the connector-poll cursor, reads bounded
provider pages, and sends only adapter-normalized records through the existing
resolve-or-quarantine sink. Records that cannot be safely matched can be
recorded in the quarantine ledger with their remote identifiers, a payload
digest, and a human-readable reason. The digest is a reference for comparison,
not a copy of the provider payload. An operator can mark a quarantined record
resolved after reviewing its identity decision.

### Poll cursor leases

Migration v6 adds nullable internal `lease_token` and `lease_expires_at` columns
to each sync cursor. They are fencing metadata, not public cursor fields: the
cursor model and `/ingestion/sync-cursors` response continue to expose only the
connector, cursor value, status, historical successful-sync time, and update
time.

A poll worker claims a cursor in one `BEGIN IMMEDIATE` transaction. A claim is
`granted` when the row is new or its prior lease is stale, `locked` when a fresh
lease is held, and `instance_missing` when the connector instance no longer
exists. Claiming preserves the prior cursor value and `last_synced_at`, including
for legacy `syncing` rows whose expiry is null. Finishing is fenced by the
claim token and releases both lease columns; a stale worker cannot finish over
its successor. Degraded and failed finishes preserve the historical successful
sync time, while a clean idle finish may provide a new one.

The legacy `upsert_sync_cursor` writer refuses to overwrite a live lease. This
store slice does not introduce an incremental provider cursor; that behavior
remains future work (including the planned A-PR6 cursor semantics). Provider
timestamps still default to the persisted record write time. The poller uses a
soft monotonic deadline: one in-flight provider request may run to its client
timeout, but retry sleeps are clipped to the remaining budget.

### Poll lifecycle and status

Only a `ready` response with HTTP 2xx and `raw_count == 0` is end-of-pages. A
page with raw rows continues the sweep even when every normalized row is
dropped. Any dropped row, transient provider condition, deadline exhaustion, or
page-cap exhaustion makes the sweep `degraded`; that degradation is sticky
through a later valid empty page. Blocked reads, throttling, timeouts, connect
failures, and 5xx responses are degraded. Redirects, malformed envelopes,
configuration or authentication failures, inactive instances, and sink
invariant failures are `failed`. A verified 2xx empty page with no drops is
`idle`.

Before each non-empty page is sent to the sink, the poller re-reads the
internal lease token and expiry. If another worker has taken the lease, the
stale sweep stops before another page write and finishes as degraded. This
pragmatic fence bounds a stale worker to at most one in-flight page; the next
full sweep corrects that page through the idempotent provider upsert. Atomic
in-sink token fencing remains future work (A-PR6).

Connector-ingested tickets follow a resolve-then-write path. The identity key
is the trimmed, case-sensitive pair `(connector instance, provider ticket ID)`,
so two provider estates can use the same remote ticket ID safely. WAIT uses
only one verified mapping for the connector instance, requires the mapped
client and connector instance to be active and consistent, and ignores any
caller-supplied ticket ID or client assignment. A deterministic internal ID is
computed for new records; an existing legacy row is updated in place and its
persisted ID is used for status history and audit records.

Without a verified mapping, the ticket is kept out of client data, persisted
under the reserved `__quarantine__` tenant, and recorded in the unmapped
ledger. Repeating the same unresolved ticket updates its latest digest and
reason and increments its occurrence count. Mapping verification re-tenants
matching tickets and seeds their initial status history; provenance-less
legacy quarantine rows have an operator-only per-ticket reclassification path.
Local/file ingestion is a separate path: it requires an explicit active
`client_id`, rejects any connector provenance, sets the source to local, and
refuses to overwrite another client's or a connector-owned row.

Canonical assets are unique per tenant by `(client_id, canonical_id)`, so the
same canonical asset identifier can exist for different clients without a
cross-tenant collision. Existing unscoped lookups remain available for
backward compatibility; new tenant-aware paths pass the client identifier.
