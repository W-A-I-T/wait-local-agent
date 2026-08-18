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
POST /consultant/blueprints/{blueprint_id}/generate-playbook
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
It also returns deterministic `decisions` for every architecture component.
Each decision records the selected implementation target, alternatives,
dependencies, systems, required permissions and licenses (including explicit
`unknown` evidence when the local catalog cannot verify them), and consumes
explicit discovery declarations for reads, changes, approvals, licenses, data
residency, data movement, and rollback expectations. Those declarations are
marked as customer evidence and are never upgraded to provider verification.
Each decision also reports read/write behavior, approvals, risk, data
movement, execution boundary, complexity, reversibility, testing, deployment
requirements, and evidence. A decision is not treated as ready merely because a target name is available: unresolved
connector bindings, provider authorization, missing templates, and unsupported
deployment surfaces remain `needs_review` or `unsupported`.
Blueprints may also carry an optional `environment` array from
`/consultant/environment-discovery`. Each record includes a bounded system
identity, connector boundary when known, status, evidence, and limitations.
`configured`, `detected`, and `permission-limited` are not equivalent to
provider authorization; the architecture view preserves that distinction and
requires review until provider evidence reaches a supported verified state.
The canonical synthetic employee-onboarding fixture at
`examples/consultant/employee-onboarding-blueprint.json` demonstrates this
promotion boundary across discovery, environment evidence, architecture,
controlled local evaluation, governance, delivery, and approval creation. Its
Power Platform targets intentionally remain `needs_review`; the fixture does
not claim live provider access or deployment. The companion
`examples/consultant/employee-onboarding-child-agent-map.json` declares the
identity, licensing, Intune, PSA, RMM, documentation, and communications
children and explicitly maps their target tools to a `ticket-triage` local
fixture stand-in.
For blueprints with multiple agents, the same response includes a supervisor
plan that labels each child agent and permits only bounded structured results
within the blueprint tenant; blueprint creation still does not create or run
those agents. The separate `/consultant/supervisor/run` operation can execute
explicitly selected persisted child definitions through the existing approval
and audit runtime.

Power Platform connector, Power Apps, Power Automate, and Copilot Studio
handoff plans are available as separate review-only artifacts. The Copilot
Studio plan records bounded topics, trigger phrases, knowledge references, and
connector actions, but it does not provision a Copilot, acquire credentials,
publish a channel, or call Microsoft services. MCP server/client and Work IQ
integration are also available behind explicit configuration. Production
deployment remains a separate approval-gated operation.
