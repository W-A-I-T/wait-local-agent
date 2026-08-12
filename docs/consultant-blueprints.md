# Consultant solution blueprints

WAIT Local Agent can store an inspectable solution blueprint for a proposed
Microsoft 365 or MSP automation solution. A blueprint is a local design
artifact: it describes the business goal, users, knowledge, systems, proposed
agents, deterministic workflows, approval boundaries, deployment targets, and
risk level. Creating or reading one does not call Microsoft services, invoke a
tool, execute a workflow, or deploy a solution.

The API exposes the artifact through authenticated routes:

```text
POST /consultant/blueprints
GET  /consultant/blueprints
GET  /consultant/blueprints/{blueprint_id}
```

Technicians can create a blueprint and viewers can inspect it. Every record is
scoped to a `client_id`; non-admin callers are bound to the tenant in their
authenticated settings. Administrators may explicitly filter a tenant, while
an administrator without a configured tenant may inspect all local records.

The CLI accepts the same bounded structure as a JSON file:

```bash
wait-local-agent consultant blueprints create blueprint.json --client-id acme
wait-local-agent consultant blueprints list --client-id acme
wait-local-agent consultant blueprints show bp_<id>
```

Blueprint validation is deterministic and rejects unknown fields, unbounded
collections, invalid identifiers, unsupported risk values, and credential-like
fields. This surface intentionally does not accept connector credentials or
arbitrary extension blobs. The existing local Store redaction also applies
when the JSON payload is persisted or exported, so secret-like text in valid
free-text fields may be redacted. Natural-language discovery, Microsoft Graph,
Copilot Studio, MCP, Power Platform packaging, deployment, and execution are
follow-up capabilities and are not implied by a stored blueprint.
