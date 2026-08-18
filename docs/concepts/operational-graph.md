# Client Operational Graph

The Client Operational Graph stores deterministic relationships between a
client's external entities. Migration v7 adds two tables:

- `external_entity_refs` identifies a user, device, ticket, or other supported
  entity by `(client_id, source_system, entity_type, external_id)`.
- `entity_links` records a typed, provenance-bearing relationship between two
  references in the same client scope.

The graph does not infer relationships with machine learning or free-text
guessing. Entity and link types are validated by the Python store boundary,
and seeders use only explicit ticket fields, canonical-asset fields, and RMM
inventory. RMM devices and alerts are client-scoped references, with an
explicit `alerted_on` link from each alert to its known device. RMM sync is
deterministic and idempotent, and provider failures return a bounded degraded
summary rather than raising. PR1 seeds ticket-to-requester and
canonical-asset-to-device relationships, plus an owner-to-device relationship
when an asset owner is present.

Every graph read is explicitly scoped. A missing scope fails closed, and a
link cannot be written when either endpoint is outside the requested client.
The operational graph service uses stable-order breadth-first traversal with
hard depth and node limits. `GET /tickets/{id}/context` requires viewer access
and returns 404 when the ticket is absent from the caller's scope, without
disclosing whether another client has it.

`GET /clients/{id}/graph` returns a bounded graph view with the same
fail-closed client boundary. MSP operators can trigger the provider read with
`POST /clients/{id}/graph/sync-rmm`; live provider reads require the existing
HTTP probing gate.
