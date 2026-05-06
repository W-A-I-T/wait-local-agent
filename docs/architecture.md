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

- Local file ingestion for Markdown, plain text, and text-based PDFs.
- Stable source references with document paths and excerpts.
- SQLite FTS5 retrieval.
- Planned vector backends: Qdrant and pgvector.

## Ticket Intelligence

- Deterministic classification and drafting for repeatable demos and tests.
- Optional local OpenAI-compatible chat-completions provider for Ollama, vLLM,
  or similar local endpoints.
- Provider failures fall back to deterministic output so ticket summaries remain
  available offline.
- Saved approval state and approval comments.

## Connectors

- HaloPSA is the first PSA wedge.
- Connector status is exposed through API and CLI before live synchronization.
- HaloPSA write operations start as safe drafts that create approval requests.
- Hudu, IT Glue, SharePoint, RMM, and M365/Entra are staged after the PSA wedge.

## Workflows

- Workflow templates define trigger, action, description, and approval policy.
- Workflow runs persist status, message, approval request, and event history.
- Initial templates cover ticket triage, technician assignment, inactive ticket
  follow-up, P1 alerts, and documentation-assisted responses.

## Control Plane

- Human approval queue for connector and workflow actions.
- Event history for workflow executions, approval decisions, and audit-friendly
  troubleshooting.
- Immutable audit events for local state transitions.
- Future RBAC, encrypted secrets, audit export, and update channel.
