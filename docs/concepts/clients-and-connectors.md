# Clients and connector instances

WAIT keeps client identity separate from provider configuration. The local
client directory is the authority for which organizations the runtime knows
about. Existing tickets and discovered assets continue to use their current
storage and behavior; this directory is additive groundwork for later
ingestion and reconciliation work.

## Client directory

Each client has a name and a lifecycle status: active, archived, or
quarantine. The reserved **Unmapped / Quarantine** entry is created when the
runtime starts. It gives future ingestion a visible, reviewable destination
for records whose provider identity has not been safely matched to a client.

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

The existing boot-time Settings connector configuration remains in place in
this phase. Connector instances are introduced alongside it and are not yet
used to drive ingestion.

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
kind. A cursor describes progress and health only; this slice does not start a
provider poller or write provider records automatically. Records that cannot
be safely matched can be recorded in the quarantine ledger with their remote
identifiers, a payload digest, and a human-readable reason. The digest is a
reference for comparison, not a copy of the provider payload. An operator can
mark a quarantined record resolved after reviewing its identity decision.

Canonical-asset uniqueness is unchanged in this slice. A future migration will
address tenant-aware uniqueness separately after its upsert and lookup paths
are revised together.
