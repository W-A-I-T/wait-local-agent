# Consultant solution blueprints

WAIT Local Agent can store an inspectable solution blueprint for a proposed
Microsoft 365 or MSP automation solution. A blueprint is a local design
artifact: it describes the business goal, users, knowledge, systems, proposed
agents, deterministic workflows, approval boundaries, deployment targets, and
risk level. It can also carry bounded agent instructions, intents, skills,
model choice, and orchestration mode (`single_agent`, `supervisor`,
`event_driven`, or `hybrid`). Creating or reading one does not call Microsoft
services, invoke a tool, execute a workflow, or deploy a solution.

The API exposes the artifact through authenticated routes:

```text
POST /consultant/blueprints
GET  /consultant/blueprints
GET  /consultant/blueprints/{blueprint_id}
GET  /consultant/blueprints/{blueprint_id}/architecture
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
wait-local-agent consultant blueprints architect bp_<id>
```

The dashboard's **Consultant** page provides the same tenant-scoped list and a
read-only architecture/workflow sequence view. It does not create credentials,
invoke tools, run workflows, or deploy solutions.

Blueprint validation is deterministic and rejects unknown fields, unbounded
collections, invalid identifiers, unsupported risk values, and credential-like
fields. This surface intentionally does not accept connector credentials or
arbitrary extension blobs. The existing local Store redaction also applies
when the JSON payload is persisted or exported, so secret-like text in valid
free-text fields may be redacted. The separate discovery intake captures
explicit requirements and produces a reviewable candidate without inferring
systems, permissions, or deployment targets.

The `architecture` view is the next governed design step. It resolves requested
agent tools and workflow IDs against the existing local smart-action and
workflow-template catalogs. Knowledge sources, external systems, and deployment
targets remain explicit review items unless they are a supported local surface
(`local`, `api`, `cli`, `agents`, or `mcp`). The response reports `ready` or
`needs_review` and always states that execution and deployment have not started.
For blueprints with multiple agents, the same response includes a supervisor
plan that labels each child agent and permits only bounded structured results
within the blueprint tenant; blueprint creation still does not create or run
those agents. The separate `/consultant/supervisor/run` operation can execute
explicitly selected persisted child definitions through the existing approval
and audit runtime.

Power Platform connector, Power Apps, and Power Automate plans are available as
separate review-only artifacts. MCP server/client and Work IQ integration are
also available behind explicit configuration. None of those plans or adapters
implicitly call Microsoft services, acquire credentials, or deploy a solution;
live Copilot Studio channel integration and production deployment remain
explicitly separate operations.
