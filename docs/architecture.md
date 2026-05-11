# Architecture

WAIT Local Agent is a local-first MSP automation appliance composed of six
layers.

## Runtime

- FastAPI operator API.
- Typer command line interface.
- SQLite state store mounted as a local appliance volume.
- Docker Compose packaging for API, dashboard, health checks, and backups.
- Safe-by-default configuration: write actions, HTTP probing, cloud fallback,
  and model inference are all disabled unless explicitly configured.

## Knowledge

- Local file ingestion for Markdown, plain text, and PDFs.
- Built-in parser path for text-based PDFs, with optional Docling parsing and
  OCR enabled only when the optional dependency and runtime flag are present.
- Stable source references with document paths and excerpts.
- SQLite FTS5 retrieval by default.
- Optional Qdrant vector backend for local embedded storage or a configured
  Qdrant service. SQLite remains the conservative fallback.

## Ticket Intelligence

- Deterministic classification and drafting for repeatable demos and tests.
- Optional local OpenAI-compatible chat-completions provider for Ollama, vLLM,
  or similar local endpoints.
- Provider failures fall back to deterministic output so ticket summaries remain
  available offline.
- Saved approval state and approval comments.

## Connectors

- HaloPSA is the first PSA wedge.
- Connector status and read-only HaloPSA health/list/read calls are exposed
  through API and CLI.
- HaloPSA write operations start as safe drafts, require approval, and then
  execute through the connector only when both HTTP probing and write-action
  flags are enabled.
- Hudu is the documentation wedge and is read-only: it can provide knowledge
  lookup context when configured, but it does not expose write operations.
- IT Glue, SharePoint, RMM, and M365/Entra are staged after the PSA and
  documentation read paths.

## Workflows

- Workflow templates define trigger, action, description, and approval policy.
- Workflow runs persist status, message, approval request, and event history.
- Initial templates cover ticket triage, technician assignment, inactive ticket
  follow-up, P1 alerts, and documentation-assisted responses.

## Control Plane

- Human approval queue for connector and workflow actions.
- Approval requests preserve the proposed connector payload for technician
  preview before any live side effect.
- Technicians can reject, approve, or revise a draft through the draft/edit
  flow before execution is attempted.
- Sanitized HaloPSA write execution metadata on approval requests.
- Event history for workflow executions, approval decisions, and audit-friendly
  troubleshooting.
- Immutable audit events for local state transitions.
- Future RBAC, encrypted secrets, audit export, and update channel.
