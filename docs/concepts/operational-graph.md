# Client Operational Graph

The Client Operational Graph stores deterministic relationships between a
client's external entities. Migration v7 adds two tables:

- `external_entity_refs` identifies a user, device, ticket, or other supported
  entity by `(client_id, source_system, entity_type, external_id)`.
- `entity_links` records a typed, provenance-bearing relationship between two
  references in the same client scope.

The graph does not infer relationships with machine learning or free-text
guessing. Entity and link types are validated by the Python store boundary,
and seeders use only explicit ticket fields and canonical-asset fields. PR1
seeds ticket-to-requester and canonical-asset-to-device relationships, plus an
owner-to-device relationship when an asset owner is present.

Every graph read is explicitly scoped. A missing scope fails closed, and a
link cannot be written when either endpoint is outside the requested client.
The operational graph service uses stable-order breadth-first traversal with
hard depth and node limits. `GET /tickets/{id}/context` requires viewer access
and returns 404 when the ticket is absent from the caller's scope, without
disclosing whether another client has it.
